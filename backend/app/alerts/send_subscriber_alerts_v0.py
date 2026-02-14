from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.admin_settings import get_setting
from app.alerts.subscriber_alerts_v0 import (
    SubscriberAlertPolicy,
    build_subscriber_alert_run_v0,
    render_daily_email_plain_v0,
)
from app.models import AlertDelivery, AlertItem, AlertRun, Subscriber
from app.notifications.email_smtp import EmailSendError, send_email_smtp
from app.settings import settings
from app.subscriptions import issue_token


@dataclass(frozen=True)
class SendAlertsResult:
    run_id: str
    status: str  # draft|sent|skipped
    subscribers_seen: int
    sent: int
    failed: int
    skipped: int
    changed: bool


def _resolve_policy(session: Session, policy: Optional[SubscriberAlertPolicy]) -> SubscriberAlertPolicy:
    if policy is not None:
        return policy
    cfg = get_setting(session, "subscriber_alert_policy_v0") or {}
    if isinstance(cfg, dict) and cfg:
        return SubscriberAlertPolicy(
            max_items=int(cfg.get("max_items", SubscriberAlertPolicy.max_items)),
            min_confidence=float(cfg.get("min_confidence", SubscriberAlertPolicy.min_confidence)),
            min_score_buy=int(cfg.get("min_score_buy", SubscriberAlertPolicy.min_score_buy)),
            min_score_sell=int(cfg.get("min_score_sell", SubscriberAlertPolicy.min_score_sell)),
            fresh_days=int(cfg.get("fresh_days", SubscriberAlertPolicy.fresh_days)),
        )
    return SubscriberAlertPolicy()


def _signature(session: Session, run_id: str) -> tuple[tuple[str, str], ...]:
    rows = list(
        session.exec(select(AlertItem.ticker, AlertItem.action).where(col(AlertItem.run_id) == run_id)).all()
    )
    return tuple(sorted(((t, a) for (t, a) in rows if t and a)))


def build_draft_subscriber_alert_run_v0(
    *,
    session: Session,
    as_of: Optional[datetime] = None,
    policy: Optional[SubscriberAlertPolicy] = None,
) -> AlertRun:
    """
    Manual-only flow:
    - Build an auditable alert_run + items as a DRAFT (no email sends).
    - Store diff vs the most recent non-draft run.
    """

    pol = _resolve_policy(session, policy)
    run_as_of = as_of or datetime.utcnow()
    run: AlertRun = build_subscriber_alert_run_v0(session=session, as_of=run_as_of, policy=pol)
    run.status = "draft"

    prev_run = session.exec(
        select(AlertRun)
        .where(col(AlertRun.id) != run.id)
        .where(col(AlertRun.status) != "draft")
        .order_by(col(AlertRun.created_at).desc())
    ).first()

    cur_sig = _signature(session, run.id)
    prev_sig: tuple[tuple[str, str], ...] = tuple()
    changed = True
    if prev_run is not None:
        prev_sig = _signature(session, prev_run.id)
        changed = cur_sig != prev_sig

    run.policy = dict(run.policy or {})
    run.policy.setdefault("daily_key", run_as_of.date().isoformat())
    run.policy["diff"] = {
        "changed": bool(changed),
        "prev_run_id": prev_run.id if prev_run else None,
        "cur_count": len(cur_sig),
        "prev_count": len(prev_sig),
    }

    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def send_subscriber_alert_run_v0(
    *,
    session: Session,
    run_id: str,
    limit_subscribers: int = 0,
    force_send: bool = False,
) -> SendAlertsResult:
    """
    Send a previously-built draft alert_run to active subscribers.
    Idempotent: does not double-send for the same run+subscriber.
    """

    run = session.exec(select(AlertRun).where(col(AlertRun.id) == run_id)).first()
    if run is None:
        raise ValueError("alert_run not found")

    if run.status != "draft":
        # Already finalized; return counts as 0 (admin can inspect history).
        return SendAlertsResult(
            run_id=run.id,
            status=run.status,
            subscribers_seen=0,
            sent=0,
            failed=0,
            skipped=0,
            changed=bool((run.policy or {}).get("diff", {}).get("changed", True)) if isinstance(run.policy, dict) else True,
        )

    diff = (run.policy or {}).get("diff") if isinstance(run.policy, dict) else None
    changed = True
    if isinstance(diff, dict) and diff.get("changed") is False:
        changed = False
    if force_send:
        changed = True

    now = datetime.utcnow()

    if not changed:
        run.status = "skipped"
        run.sent_at = now
        session.add(run)
        session.commit()
        return SendAlertsResult(
            run_id=run.id,
            status=run.status,
            subscribers_seen=0,
            sent=0,
            failed=0,
            skipped=0,
            changed=False,
        )

    stmt = select(Subscriber).where(col(Subscriber.status) == "active").order_by(col(Subscriber.created_at))
    if limit_subscribers and limit_subscribers > 0:
        stmt = stmt.limit(limit_subscribers)
    subs = list(session.exec(stmt).all())

    subscribers_seen = len(subs)
    sent = 0
    failed = 0
    skipped = 0

    for s in subs:
        existing = session.exec(
            select(AlertDelivery.id).where(col(AlertDelivery.run_id) == run.id, col(AlertDelivery.subscriber_id) == s.id)
        ).first()
        if existing is not None:
            skipped += 1
            continue

        unsub_tok = issue_token(session=session, subscriber_id=s.id, purpose="unsubscribe", ttl_hours=24 * 365 * 2)
        unsub_url = f"{settings.public_base_url.rstrip('/')}/unsubscribe?token={unsub_tok.token}"

        subject, body = render_daily_email_plain_v0(session=session, run=run, unsubscribe_url=unsub_url)

        delivery = AlertDelivery(run_id=run.id, subscriber_id=s.id, status="queued")
        session.add(delivery)
        session.commit()
        session.refresh(delivery)

        try:
            send_email_smtp(to_email=s.email, subject=subject, text_body=body)
            delivery.status = "sent"
            delivery.sent_at = datetime.utcnow()
            sent += 1
        except EmailSendError as e:
            delivery.status = "failed"
            delivery.error = str(e)
            failed += 1

        session.add(delivery)
        session.commit()

    run.status = "sent"
    run.sent_at = now
    session.add(run)
    session.commit()

    return SendAlertsResult(
        run_id=run.id,
        status=run.status,
        subscribers_seen=subscribers_seen,
        sent=sent,
        failed=failed,
        skipped=skipped,
        changed=True,
    )


def build_draft_subscriber_alert_run_from_tickers_v0(
    *,
    session: Session,
    source_run_id: str,
    tickers: list[str],
) -> AlertRun:
    """
    Creates a new DRAFT alert_run containing a subset of items from an existing run.
    Used for per-alert "Send" in the admin UI.
    """

    src = session.exec(select(AlertRun).where(col(AlertRun.id) == source_run_id)).first()
    if src is None:
        raise ValueError("source alert_run not found")

    want = {t.strip().upper() for t in tickers if isinstance(t, str) and t.strip()}
    if not want:
        raise ValueError("no tickers provided")

    src_items = list(session.exec(select(AlertItem).where(col(AlertItem.run_id) == src.id)).all())
    picked = [it for it in src_items if (it.ticker or "").strip().upper() in want]
    if not picked:
        raise ValueError("no matching items in source run")

    run = AlertRun(
        as_of=src.as_of,
        status="draft",
        policy={
            "mode": "manual_single",
            "source_run_id": src.id,
            "tickers": sorted({it.ticker for it in picked if it.ticker}),
            "diff": {"changed": True, "note": "manual_single forces send"},
        },
        source_runs=dict(src.source_runs or {}),
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    for it in picked:
        session.add(
            AlertItem(
                run_id=run.id,
                ticker=it.ticker,
                action=it.action,
                segment=it.segment,
                score=it.score,
                confidence=it.confidence,
                why=list(it.why or []),
                evidence=dict(it.evidence or {}),
            )
        )
    session.commit()
    return run
