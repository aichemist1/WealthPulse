from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import AlertItem, AlertRun, SnapshotRecommendation, SnapshotRun


@dataclass(frozen=True)
class SubscriberAlertPolicy:
    max_items: int = 5
    min_confidence: float = 0.30
    min_score_buy: int = 75
    min_score_sell: int = 35
    fresh_days: int = 7


def _latest_run(session: Session, kind: str) -> Optional[SnapshotRun]:
    return session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == kind)
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()


def _money(v: Any) -> str:
    try:
        x = float(v)
    except Exception:
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1_000_000_000:
        return f"{sign}${x/1_000_000_000:.1f}B"
    if x >= 1_000_000:
        return f"{sign}${x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"{sign}${x/1_000:.1f}K"
    return f"{sign}${x:,.0f}"


def _build_why(*, r: SnapshotRecommendation) -> list[str]:
    reasons = r.reasons or {}

    if "Fresh whale" in (reasons.get("signal") or ""):
        sc13 = reasons.get("sc13") or {}
        insider = reasons.get("insider") or {}
        trend = reasons.get("trend") or {}
        out = []
        sc13_count = int(sc13.get("count") or 0)
        if sc13_count:
            out.append(f"SC13 filings: {sc13_count} (latest {str(sc13.get('latest_filed_at') or '')[:10]})")
        net = insider.get("net_value")
        if net is not None:
            out.append(f"Insider net: {_money(net)} (buy {_money(insider.get('buy_value'))} / sell {_money(insider.get('sell_value'))})")
        if trend:
            close = trend.get("close")
            sma50 = trend.get("sma50")
            ret20 = trend.get("return_20d")
            if close is not None and sma50 is not None and ret20 is not None:
                out.append(f"Trend: close {close:.2f} vs SMA50 {sma50:.2f}, 20D {float(ret20)*100:.1f}%")
        return out[:4]

    # 13F-based top picks
    delta = reasons.get("delta_value_usd")
    breadth = reasons.get("breadth") or {}
    corro = reasons.get("corroborators") or {}
    trend_adj = reasons.get("trend_adjustment")
    out = [
        f"13F accumulation (delayed): Δ value {_money(delta)}",
        f"Managers increasing: {int(breadth.get('increase') or 0)}/{int(breadth.get('total') or 0)}",
    ]
    out.append(
        "Corroborators: "
        + ", ".join(
            [
                f"SC13={'yes' if corro.get('sc13_recent') else 'no'}",
                f"InsiderBuy={'yes' if corro.get('insider_buy_recent') else 'no'}",
                f"TrendBull={'yes' if corro.get('trend_bullish_recent') else 'no'}",
            ]
        )
    )
    if trend_adj is not None:
        out.append(f"Timing adjust: {int(trend_adj):+d} (trend)")
    return out[:4]


def build_subscriber_alert_run_v0(
    *,
    session: Session,
    as_of: Optional[datetime] = None,
    policy: Optional[SubscriberAlertPolicy] = None,
) -> AlertRun:
    """
    Create and persist a v0 subscriber AlertRun + AlertItems from the latest snapshots.

    BUY/SELL only:
    - BUY: action == buy (from fresh_signals_v0 or recommendations_v0)
    - SELL: action == avoid (mapped to sell) from fresh_signals_v0
    """

    pol = policy or SubscriberAlertPolicy()
    as_of_dt = as_of or datetime.utcnow()

    fresh_run = _latest_run(session, "fresh_signals_v0")
    recs_run = _latest_run(session, "recommendations_v0")

    candidates: list[SnapshotRecommendation] = []
    if fresh_run is not None:
        candidates.extend(
            list(
                session.exec(
                    select(SnapshotRecommendation)
                    .where(col(SnapshotRecommendation.run_id) == fresh_run.id)
                    .order_by(col(SnapshotRecommendation.score).desc(), col(SnapshotRecommendation.confidence).desc())
                ).all()
            )
        )
    if recs_run is not None:
        candidates.extend(
            list(
                session.exec(
                    select(SnapshotRecommendation)
                    .where(col(SnapshotRecommendation.run_id) == recs_run.id)
                    .order_by(col(SnapshotRecommendation.score).desc(), col(SnapshotRecommendation.confidence).desc())
                ).all()
            )
        )

    # Convert to BUY/SELL only and rank.
    picked: list[SnapshotRecommendation] = []
    used: set[str] = set()
    for r in candidates:
        if r.ticker in used:
            continue
        if float(r.confidence) < pol.min_confidence:
            continue
        if r.action == "buy" and int(r.score) >= pol.min_score_buy:
            picked.append(r)
            used.add(r.ticker)
        elif r.action == "avoid" and int(r.score) <= pol.min_score_sell:
            picked.append(r)
            used.add(r.ticker)
        if len(picked) >= pol.max_items:
            break

    run = AlertRun(
        as_of=as_of_dt,
        policy={
            "max_items": pol.max_items,
            "min_confidence": pol.min_confidence,
            "min_score_buy": pol.min_score_buy,
            "min_score_sell": pol.min_score_sell,
            "fresh_days": pol.fresh_days,
        },
        source_runs={
            "fresh_signals_v0": fresh_run.id if fresh_run else None,
            "recommendations_v0": recs_run.id if recs_run else None,
        },
    )
    session.add(run)
    session.flush()

    for r in picked:
        action = "buy" if r.action == "buy" else "sell"
        session.add(
            AlertItem(
                run_id=run.id,
                ticker=r.ticker,
                action=action,
                segment=r.segment,
                score=int(r.score),
                confidence=float(r.confidence),
                why=_build_why(r=r),
                evidence={
                    "snapshot_run_id": r.run_id,
                    "signal": (r.reasons or {}).get("signal"),
                    "as_of": (r.reasons or {}).get("as_of"),
                },
            )
        )

    session.commit()
    session.refresh(run)
    return run


def render_daily_email_v0(*, session: Session, run: AlertRun, unsubscribe_url: str = "") -> tuple[str, str]:
    """
    Returns (subject, text_body). Keep v0 plain-text for pilot.
    """

    items = list(
        session.exec(select(AlertItem).where(col(AlertItem.run_id) == run.id).order_by(col(AlertItem.score).desc())).all()
    )

    if not items:
        subject = "WealthPulse Daily Signals (No picks today)"
        body = (
            "WealthPulse Daily Signals\n\n"
            f"As of: {run.as_of.isoformat()}\n\n"
            "No BUY/SELL signals met today's thresholds.\n\n"
            + (f"Unsubscribe: {unsubscribe_url}\n\n" if unsubscribe_url else "")
            + "This is educational content only, not financial advice."
        )
        return subject, body

    lines: list[str] = []
    lines.append("WealthPulse Daily Signals")
    lines.append("")
    lines.append(f"As of: {run.as_of.isoformat()}")
    lines.append("")
    for i, it in enumerate(items, start=1):
        lines.append(f"{i}. {it.ticker} — {it.action.upper()} (score {it.score}, conf {int(it.confidence*100)}%)")
        for w in (it.why or [])[:4]:
            lines.append(f"   - {w}")
    lines.append("")

    if unsubscribe_url:
        lines.append(f"Unsubscribe: {unsubscribe_url}")
    lines.append("Disclosures: Educational content only; not financial advice. Filings may be delayed (13F).")
    subject = f"WealthPulse Daily Signals ({len(items)} picks)"
    return subject, "\n".join(lines)


def _wrap(text: str, width: int = 88) -> str:
    """
    Lightweight wrapper for plain-text email lines.
    Avoids hard dependency on external libs; keeps readability.
    """
    import textwrap

    return "\n".join(textwrap.wrap(text, width=width, replace_whitespace=False, drop_whitespace=False))


def render_daily_email_plain_v0(
    *,
    session: Session,
    run: AlertRun,
    unsubscribe_url: str = "",
) -> tuple[str, str]:
    """
    Plain-text only email (pilot).
    Keep copy scannable on mobile.
    Pilot format: minimal fields only (Ticker, Action, Score, Conf).
    """

    items = list(
        session.exec(select(AlertItem).where(col(AlertItem.run_id) == run.id).order_by(col(AlertItem.score).desc())).all()
    )

    def _row(it: AlertItem) -> str:
        conf_pct = int(round(float(it.confidence or 0.0) * 100))
        return f"{it.ticker}\t{it.action.upper()}\t{int(it.score)}\t{conf_pct}%"

    lines: list[str] = []
    lines.append("WealthPulse Daily Signals")
    lines.append(f"As of: {run.as_of.isoformat()}")
    lines.append("")

    if not items:
        lines.append("No BUY/SELL signals met today's thresholds.")
    else:
        lines.append("Ticker\tAction\tScore\tConf")
        for it in items:
            lines.append(_row(it))
        lines.append("")

    if unsubscribe_url:
        lines.append(f"Unsubscribe: {unsubscribe_url}")
    lines.append("Disclosures: Educational content only; not financial advice. Filings may be delayed (13F).")

    subject = f"WealthPulse Daily Signals ({len(items)} picks)"
    return subject, "\n".join(lines).strip() + "\n"
