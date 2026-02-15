import json
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from sqlmodel import col

from app.db import get_session, init_db
from app.models import (
    AdminAlert,
    AdminSetting,
    Institution13FHolding,
    Institution13FReport,
    DividendMetrics,
    Security,
    Snapshot13FWhale,
    SnapshotInsiderWhale,
    SnapshotRun,
    Stock,
    SnapshotRecommendation,
    AlertRun,
    AlertItem,
    AlertDelivery,
    Subscriber,
    SubscriberToken,
)
from app.settings import settings
from app.snapshot.watchlists import compute_watchlist, parse_ticker_csv
from app.snapshot.segments_v0 import compute_segments_v0
from app.subscriptions import confirm_subscription, issue_token, normalize_email, unsubscribe, upsert_subscriber
from app.notifications.email_smtp import send_email_smtp, EmailSendError
from app.alerts.subscriber_alerts_v0 import build_subscriber_alert_run_v0, render_daily_email_plain_v0, SubscriberAlertPolicy
from app.alerts.send_subscriber_alerts_v0 import (
    build_draft_subscriber_alert_run_v0,
    build_draft_subscriber_alert_run_from_tickers_v0,
    send_subscriber_alert_run_v0,
)
from app.admin_settings import get_setting, set_setting
from app.auth_admin import admin_secret, issue_admin_token, verify_bearer_header, verify_admin_token


app = FastAPI(title="WealthPulse API", version="0.1.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def _admin_auth_middleware(request, call_next):
    """
    Pilot admin auth: protects /admin/* endpoints when WEALTHPULSE_ADMIN_PASSWORD is set.
    """

    if not (settings.admin_password or "").strip():
        return await call_next(request)

    path = request.url.path or ""
    if not path.startswith("/admin"):
        return await call_next(request)

    # Allow preflight and auth bootstrap endpoints.
    if request.method.upper() == "OPTIONS":
        return await call_next(request)
    if path.startswith("/admin/auth/status") or path.startswith("/admin/auth/login"):
        return await call_next(request)

    secret = admin_secret(admin_password=settings.admin_password, admin_token_secret=settings.admin_token_secret)
    if not secret:
        return JSONResponse({"detail": "Admin auth misconfigured."}, status_code=500)

    if not verify_bearer_header(secret=secret, authorization=request.headers.get("Authorization", "")):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)


@app.get("/admin/auth/status")
def admin_auth_status() -> dict:
    enabled = bool((settings.admin_password or "").strip())
    return {"enabled": enabled, "ttl_hours": settings.admin_token_ttl_hours}


@app.post("/admin/auth/login")
def admin_login(payload: dict) -> dict:
    if not bool((settings.admin_password or "").strip()):
        return {"ok": False, "error": "admin auth disabled (set WEALTHPULSE_ADMIN_PASSWORD)"}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected JSON body"}
    pw = str(payload.get("password") or "")
    if pw != settings.admin_password:
        return JSONResponse({"ok": False, "error": "Invalid password"}, status_code=401)

    secret = admin_secret(admin_password=settings.admin_password, admin_token_secret=settings.admin_token_secret)
    tok = issue_admin_token(secret=secret, ttl_hours=settings.admin_token_ttl_hours)
    return {"ok": True, "token": tok.token, "expires_at": tok.expires_at}


@app.get("/admin/auth/session")
def admin_session(authorization: str = "") -> dict:
    secret = admin_secret(admin_password=settings.admin_password, admin_token_secret=settings.admin_token_secret)
    auth = authorization or ""
    # In practice FastAPI doesn't inject headers into params; this endpoint is mainly used via middleware-protected calls.
    # Keep it simple: clients can call any /admin endpoint to validate token.
    return {"ok": True}


@app.get("/admin/stocks")
def list_stocks(session: Session = Depends(get_session)) -> list[Stock]:
    return list(session.exec(select(Stock).order_by(Stock.ticker)).all())


@app.get("/admin/subscribers")
def list_admin_subscribers(status: str = "", limit: int = 200, session: Session = Depends(get_session)) -> dict:
    """
    Admin-only subscriber list for pilot ops.
    Read-only in v0 (no unsubscribe/resubscribe actions here yet).
    """

    lim = max(1, min(int(limit or 200), 1000))
    stmt = select(Subscriber).order_by(col(Subscriber.created_at).desc()).limit(lim)
    if status.strip():
        stmt = stmt.where(col(Subscriber.status) == status.strip())
    rows = list(session.exec(stmt).all())

    # Basic counts for quick ops visibility.
    counts: dict[str, int] = {}
    for s in rows:
        counts[s.status] = counts.get(s.status, 0) + 1

    return {
        "counts": counts,
        "rows": [
            {
                "email": s.email,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "confirmed_at": s.confirmed_at.isoformat() if s.confirmed_at else None,
                "unsubscribed_at": s.unsubscribed_at.isoformat() if s.unsubscribed_at else None,
            }
            for s in rows
        ],
    }


@app.post("/admin/subscribers/manual-add")
def manual_add_subscriber(payload: dict, session: Session = Depends(get_session)) -> dict:
    """
    Pilot escape hatch: add a subscriber directly to the DB without sending confirmation email.
    Useful when running locally (public URLs won't be reachable by external users).
    """

    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected JSON body"}
    email = normalize_email(str(payload.get("email") or ""))
    if not email:
        return {"ok": False, "error": "Missing email"}

    status = str(payload.get("status") or "active").strip().lower()
    if status not in {"pending", "active"}:
        return {"ok": False, "error": "status must be pending|active"}

    try:
        sub = upsert_subscriber(session=session, email=email)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    sub.status = status
    if status == "active":
        sub.confirmed_at = sub.confirmed_at or datetime.utcnow()
        sub.unsubscribed_at = None

    session.add(sub)
    session.commit()

    return {
        "ok": True,
        "email": sub.email,
        "status": sub.status,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "confirmed_at": sub.confirmed_at.isoformat() if sub.confirmed_at else None,
    }


@app.get("/admin/snapshots/insider-whales/latest")
def latest_insider_whales(session: Session = Depends(get_session)) -> dict:
    run = session.exec(
        select(SnapshotRun).where(col(SnapshotRun.kind) == "insider_whales").order_by(col(SnapshotRun.as_of).desc())
    ).first()
    if run is None:
        return {"as_of": None, "rows": []}

    rows = list(
        session.exec(
            select(SnapshotInsiderWhale)
            .where(SnapshotInsiderWhale.run_id == run.id)
            .order_by(col(SnapshotInsiderWhale.total_purchase_value).desc())
        ).all()
    )
    return {
        "as_of": run.as_of,
        "params": run.params,
        "rows": rows,
    }


@app.get("/admin/snapshots/13f-whales/latest")
def latest_13f_whales(session: Session = Depends(get_session)) -> dict:
    run = session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == "13f_whales")
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()
    if run is None:
        return {"as_of": None, "rows": []}

    rows = _get_13f_whale_rows(session=session, run_id=run.id)

    return {"as_of": run.as_of, "params": run.params, "run_id": run.id, "rows": rows}


def _get_13f_whale_rows(*, session: Session, run_id: str) -> list[dict]:
    whales = list(
        session.exec(
            select(Snapshot13FWhale)
            .where(Snapshot13FWhale.run_id == run_id)
            .order_by(col(Snapshot13FWhale.delta_value_usd).desc())
        ).all()
    )
    cusips = {r.cusip for r in whales}
    securities = list(session.exec(select(Security).where(col(Security.cusip).in_(cusips))).all()) if cusips else []
    sec_by_cusip = {s.cusip: s for s in securities}

    enriched: list[dict] = []
    for r in whales:
        sec = sec_by_cusip.get(r.cusip)
        enriched.append(
            {
                "cusip": r.cusip,
                "ticker": sec.ticker if sec else None,
                "name": sec.name if sec else None,
                "total_value_usd": r.total_value_usd,
                "delta_value_usd": r.delta_value_usd,
                "manager_count": r.manager_count,
                "manager_increase_count": r.manager_increase_count,
                "manager_decrease_count": r.manager_decrease_count,
            }
        )
    return enriched


@app.get("/admin/snapshots/runs")
def list_snapshot_runs(kind: str = "", limit: int = 50, session: Session = Depends(get_session)) -> dict:
    """
    List snapshot runs (optionally filter by kind).
    """

    # Dedupe runs for the UI: keep only the latest created run for each (kind, as_of).
    # The pipeline can regenerate the same snapshot multiple times (retries, enrichment, etc.),
    # but the admin Runs list should show one entry per snapshot time.
    stmt = select(SnapshotRun).order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc()).limit(500)
    if kind.strip():
        stmt = stmt.where(col(SnapshotRun.kind) == kind.strip())
    raw = list(session.exec(stmt).all())

    deduped: list[SnapshotRun] = []
    seen: set[tuple[str, str]] = set()
    for r in raw:
        key = (str(r.kind or ""), r.as_of.isoformat() if r.as_of else "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
        if len(deduped) >= min(max(int(limit or 50), 1), 200):
            break

    return {
        "runs": [{"id": r.id, "kind": r.kind, "as_of": r.as_of, "params": r.params, "created_at": r.created_at} for r in deduped]
    }


@app.get("/admin/snapshots/13f-whales/run/{run_id}")
def get_13f_whales_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.exec(select(SnapshotRun).where(col(SnapshotRun.id) == run_id)).first()
    if run is None or run.kind != "13f_whales":
        return {"as_of": None, "rows": []}
    return {"as_of": run.as_of, "params": run.params, "run_id": run.id, "rows": _get_13f_whale_rows(session=session, run_id=run.id)}


@app.get("/admin/snapshots/insider-whales/run/{run_id}")
def get_insider_whales_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.exec(select(SnapshotRun).where(col(SnapshotRun.id) == run_id)).first()
    if run is None or run.kind != "insider_whales":
        return {"as_of": None, "rows": []}
    rows = list(
        session.exec(
            select(SnapshotInsiderWhale)
            .where(SnapshotInsiderWhale.run_id == run.id)
            .order_by(col(SnapshotInsiderWhale.total_purchase_value).desc())
        ).all()
    )
    return {"as_of": run.as_of, "params": run.params, "run_id": run.id, "rows": rows}


@app.get("/admin/recommendations/latest")
def latest_recommendations(session: Session = Depends(get_session)) -> dict:
    run = session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == "recommendations_v0")
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()
    if run is None:
        return {"as_of": None, "rows": []}

    rows = list(
        session.exec(
            select(SnapshotRecommendation)
            .where(SnapshotRecommendation.run_id == run.id)
            .order_by(col(SnapshotRecommendation.score).desc())
        ).all()
    )
    return {"as_of": run.as_of, "params": run.params, "run_id": run.id, "rows": rows}


@app.get("/admin/fresh-signals/latest")
def latest_fresh_signals(session: Session = Depends(get_session)) -> dict:
    run = session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == "fresh_signals_v0")
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()
    if run is None:
        return {"as_of": None, "rows": []}

    rows = list(
        session.exec(
            select(SnapshotRecommendation)
            .where(SnapshotRecommendation.run_id == run.id)
            .order_by(col(SnapshotRecommendation.score).desc())
        ).all()
    )
    return {"as_of": run.as_of, "params": run.params, "run_id": run.id, "rows": rows}


@app.get("/admin/fresh-signals/run/{run_id}")
def get_fresh_signals_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    run = session.exec(select(SnapshotRun).where(col(SnapshotRun.id) == run_id)).first()
    if run is None or run.kind != "fresh_signals_v0":
        return {"as_of": None, "rows": []}

    rows = list(
        session.exec(
            select(SnapshotRecommendation)
            .where(SnapshotRecommendation.run_id == run.id)
            .order_by(col(SnapshotRecommendation.score).desc())
        ).all()
    )
    return {"as_of": run.as_of, "params": run.params, "run_id": run.id, "rows": rows}


@app.get("/admin/metrics")
def admin_metrics(session: Session = Depends(get_session)) -> dict:
    report_count_13f = session.exec(select(Institution13FReport.id)).all()
    holding_cusips = session.exec(select(Institution13FHolding.cusip)).all()
    distinct_cusips_13f = len({str(c).upper() for c in holding_cusips if c})
    mapped_security_cusips = session.exec(select(Security.cusip)).all()
    mapped_cusips = len({str(c).upper() for c in mapped_security_cusips if c})

    return {
        "counts": {
            "13f_reports": len(report_count_13f),
            "13f_distinct_cusips": distinct_cusips_13f,
            "security_mapped_cusips": mapped_cusips,
        },
        "coverage": {
            "cusip_to_ticker_ratio": (mapped_cusips / distinct_cusips_13f) if distinct_cusips_13f else None,
        },
    }


@app.get("/admin/watchlists/etfs")
def watchlist_etfs(session: Session = Depends(get_session)) -> dict:
    tickers = parse_ticker_csv(settings.watchlist_etfs)
    rows = compute_watchlist(session=session, tickers=tickers)
    as_of = max((r.as_of_date for r in rows if r.as_of_date), default=None)
    return {"as_of": as_of, "rows": rows}


@app.get("/admin/watchlists/dividends")
def watchlist_dividends(session: Session = Depends(get_session)) -> dict:
    tickers = parse_ticker_csv(settings.watchlist_dividend_stocks)
    rows = compute_watchlist(session=session, tickers=tickers)
    metrics = (
        list(
            session.exec(
                select(DividendMetrics)
                .where(col(DividendMetrics.ticker).in_(tickers), DividendMetrics.source == "yahoo_finance")
            ).all()
        )
        if tickers
        else []
    )
    m_by_ticker = {m.ticker: m for m in metrics}
    as_of = max((r.as_of_date for r in rows if r.as_of_date), default=None)

    enriched: list[dict] = []
    for r in rows:
        m = m_by_ticker.get(r.ticker)
        enriched.append(
            {
                **r.model_dump(),
                "dividend_yield_ttm": m.dividend_yield_ttm if m else None,
                "payout_ratio": m.payout_ratio if m else None,
                "ex_dividend_date": m.ex_dividend_date if m else None,
                "dividend_as_of": m.as_of.isoformat() if (m and m.as_of) else None,
            }
        )
    return {"as_of": as_of, "rows": enriched}


@app.get("/admin/alerts/latest")
def latest_alerts(unread_only: bool = False, limit: int = 30, session: Session = Depends(get_session)) -> dict:
    stmt = select(AdminAlert).order_by(col(AdminAlert.created_at).desc()).limit(min(limit, 200))
    if unread_only:
        stmt = stmt.where(AdminAlert.read_at == None)  # noqa: E711
    rows = list(session.exec(stmt).all())
    return {"rows": rows}


@app.post("/admin/alerts/{alert_id}/ack")
def ack_alert(alert_id: str, session: Session = Depends(get_session)) -> dict:
    a = session.exec(select(AdminAlert).where(AdminAlert.id == alert_id)).first()
    if a is None:
        return {"ok": False}
    a.read_at = datetime.utcnow()
    session.add(a)
    session.commit()
    return {"ok": True}


@app.get("/admin/segments/latest")
def latest_segments(session: Session = Depends(get_session)) -> dict:
    return compute_segments_v0(session=session, picks_per_segment=2)


@app.post("/subscribe")
def subscribe(payload: dict, session: Session = Depends(get_session)) -> dict:
    email = normalize_email(str(payload.get("email") or ""))
    try:
        sub = upsert_subscriber(session=session, email=email)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    tok = issue_token(session=session, subscriber_id=sub.id, purpose="confirm", ttl_hours=48)
    confirm_url = f"{settings.public_base_url.rstrip('/')}/confirm?token={tok.token}"
    unsub_tok = issue_token(session=session, subscriber_id=sub.id, purpose="unsubscribe", ttl_hours=24 * 365 * 2)
    unsub_url = f"{settings.public_base_url.rstrip('/')}/unsubscribe?token={unsub_tok.token}"

    subject = "Confirm your WealthPulse subscription"
    text = (
        "Welcome to WealthPulse!\n\n"
        "Please confirm your subscription:\n"
        f"{confirm_url}\n\n"
        f"If you didn't request this, ignore this email. To unsubscribe: {unsub_url}\n"
    )
    try:
        send_email_smtp(to_email=sub.email, subject=subject, text_body=text)
    except EmailSendError as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "status": sub.status}


@app.get("/subscribe")
def subscribe_page(request: Request) -> HTMLResponse:
    """
    Public subscribe landing page (email-only product).
    Uses the existing JSON POST /subscribe endpoint via fetch().
    """

    # Use relative POST to avoid accidentally hardcoding 127.0.0.1 or other internal hostnames.
    endpoint = "/subscribe"
    html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>WealthPulse — Subscribe</title>
    <style>
      :root {{
        --bg: #0b1020;
        --card: #111a33;
        --text: #e8ecf6;
        --muted: #9aa6c7;
        --border: rgba(255,255,255,0.10);
        --accent: rgba(138,180,255,0.9);
        --error: #ff6b6b;
      }}
      html, body {{ height: 100%; margin: 0; background: var(--bg); color: var(--text);
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }}
      .shell {{ min-height: 100%; display: grid; place-items: center; padding: 16px; }}
      .card {{ width: min(560px, 92vw); background: linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.015));
        border: 1px solid var(--border); border-radius: 14px; padding: 18px; box-shadow: 0 20px 60px rgba(0,0,0,0.35); }}
      .top {{ display: flex; gap: 12px; align-items: center; }}
      .mark {{ width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center;
        background: rgba(138,180,255,0.12); border: 1px solid rgba(138,180,255,0.25); font-weight: 800; }}
      h1 {{ font-size: 16px; margin: 0; }}
      .sub {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}
      .row {{ display: flex; gap: 10px; margin-top: 14px; }}
      input {{ flex: 1; background: rgba(0,0,0,0.25); color: var(--text); border: 1px solid var(--border);
        border-radius: 10px; padding: 10px 12px; font-size: 12px; outline: none; }}
      input:focus {{ border-color: rgba(138,180,255,0.45); }}
      button {{ background: rgba(138,180,255,0.14); color: var(--text); border: 1px solid rgba(138,180,255,0.35);
        border-radius: 10px; padding: 10px 12px; font-size: 12px; cursor: pointer; }}
      button:hover {{ background: rgba(138,180,255,0.22); border-color: rgba(138,180,255,0.55); }}
      .msg {{ margin-top: 12px; font-size: 12px; color: var(--muted); white-space: pre-wrap; }}
      .err {{ color: var(--error); }}
      .fine {{ margin-top: 10px; font-size: 12px; color: var(--muted); line-height: 1.5; }}
      a {{ color: var(--accent); text-decoration: none; }}
      a:hover {{ text-decoration: underline; }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="card">
        <div class="top">
          <div class="mark">WP</div>
          <div>
            <h1>Subscribe to WealthPulse alerts</h1>
            <div class="sub">Email-only. No dashboard access. Double opt-in.</div>
          </div>
        </div>

        <form id="f" autocomplete="on">
          <div class="row">
            <input id="email" type="email" placeholder="you@domain.com" required />
            <button type="submit">Subscribe</button>
          </div>
        </form>

        <div id="msg" class="msg"></div>
        <div class="fine">
          You’ll receive a confirmation email. Click the link to activate.<br/>
          Disclosures: Educational content only; not financial advice.
        </div>
      </div>
    </div>

    <script>
      const form = document.getElementById('f');
      const emailEl = document.getElementById('email');
      const msg = document.getElementById('msg');
      const endpoint = {json.dumps(endpoint)};

      function setMsg(text, isErr=false) {{
        msg.textContent = text;
        msg.className = 'msg' + (isErr ? ' err' : '');
      }}

      form.addEventListener('submit', async (e) => {{
        e.preventDefault();
        const email = (emailEl.value || '').trim();
        if (!email) return;
        setMsg('Sending confirmation email…');
        try {{
          const resp = await fetch(endpoint, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json', 'Accept': 'application/json' }},
            body: JSON.stringify({{ email }})
          }});
          const txt = await resp.text();
          let data = null;
          try {{ data = JSON.parse(txt); }} catch {{}}
          if (!resp.ok || (data && data.ok === false)) {{
            setMsg((data && data.error) ? data.error : txt, true);
            return;
          }}
          setMsg('Check your inbox for the confirmation link.\\nIf you don\\'t see it, check Spam/Promotions.');
          form.reset();
        }} catch (err) {{
          setMsg(String(err || 'Failed'), true);
        }}
      }});
    </script>
  </body>
</html>
""".strip()
    return HTMLResponse(html)


@app.get("/confirm")
def confirm(token: str = "", session: Session = Depends(get_session)) -> HTMLResponse:
    ok = confirm_subscription(session=session, token=token)
    if ok:
        return HTMLResponse("<h3>Subscription confirmed.</h3><p>You will receive weekday alerts.</p>")
    return HTMLResponse("<h3>Invalid or expired link.</h3>", status_code=400)


@app.get("/unsubscribe")
def unsubscribe_link(token: str = "", session: Session = Depends(get_session)) -> HTMLResponse:
    ok = unsubscribe(session=session, token=token)
    if ok:
        return HTMLResponse("<h3>Unsubscribed.</h3><p>You will no longer receive emails.</p>")
    return HTMLResponse("<h3>Invalid or expired link.</h3>", status_code=400)


@app.post("/admin/subscribers/send-test-alert")
def send_test_alert(payload: dict, session: Session = Depends(get_session)) -> dict:
    """
    Admin-only in spirit; no auth in v0.
    Sends a one-off daily alert email to a specific address (or the first active subscriber).
    """

    to_email = normalize_email(str(payload.get("email") or ""))
    if not to_email:
        s = session.exec(select(Subscriber).where(col(Subscriber.status) == "active").order_by(col(Subscriber.created_at))).first()
        if s is None:
            return {"ok": False, "error": "No active subscribers found and no email provided."}
        to_email = s.email

    # Honor admin thresholds if present.
    cfg = get_setting(session, "subscriber_alert_policy_v0") or {}
    pol = None
    if isinstance(cfg, dict) and cfg:
        pol = SubscriberAlertPolicy(
            max_items=int(cfg.get("max_items", SubscriberAlertPolicy.max_items)),
            min_confidence=float(cfg.get("min_confidence", SubscriberAlertPolicy.min_confidence)),
            min_score_buy=int(cfg.get("min_score_buy", SubscriberAlertPolicy.min_score_buy)),
            min_score_sell=int(cfg.get("min_score_sell", SubscriberAlertPolicy.min_score_sell)),
            fresh_days=int(cfg.get("fresh_days", SubscriberAlertPolicy.fresh_days)),
        )

    run = build_subscriber_alert_run_v0(session=session, policy=pol)
    # For a test send, keep it simple (no unsubscribe link).
    subject, text = render_daily_email_plain_v0(session=session, run=run, unsubscribe_url="")
    try:
        send_email_smtp(to_email=to_email, subject=subject, text_body=text)
    except EmailSendError as e:
        return {"ok": False, "error": str(e)}

    return {"ok": True, "to": to_email, "run_id": run.id}


@app.get("/admin/settings/subscriber-alert-policy-v0")
def get_subscriber_alert_policy(session: Session = Depends(get_session)) -> dict:
    v = get_setting(session, "subscriber_alert_policy_v0") or {}
    if not v:
        v = {
            "max_items": SubscriberAlertPolicy.max_items,
            "min_confidence": SubscriberAlertPolicy.min_confidence,
            "min_score_buy": SubscriberAlertPolicy.min_score_buy,
            "min_score_sell": SubscriberAlertPolicy.min_score_sell,
            "fresh_days": SubscriberAlertPolicy.fresh_days,
        }
    return {"key": "subscriber_alert_policy_v0", "value": v}


@app.post("/admin/settings/subscriber-alert-policy-v0")
def set_subscriber_alert_policy(payload: dict, session: Session = Depends(get_session)) -> dict:
    v = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(v, dict):
        return {"ok": False, "error": "Expected { value: { ... } }"}
    row = set_setting(session, "subscriber_alert_policy_v0", v)
    return {"ok": True, "updated_at": row.updated_at, "value": row.value}


@app.get("/admin/subscriber-alerts/runs")
def list_subscriber_alert_runs(days: int = 5, limit: int = 50, session: Session = Depends(get_session)) -> dict:
    """
    Last N days of subscriber alert runs (history view).
    """

    days_i = max(1, min(int(days or 5), 30))
    lim = max(1, min(int(limit or 50), 200))
    since = datetime.utcnow() - timedelta(days=days_i)

    runs = list(
        session.exec(
            select(AlertRun).where(col(AlertRun.created_at) >= since).order_by(col(AlertRun.created_at).desc()).limit(lim)
        ).all()
    )
    out = []
    for r in runs:
        items_count = session.exec(select(AlertItem.id).where(col(AlertItem.run_id) == r.id)).all()
        dels = list(session.exec(select(AlertDelivery.status).where(col(AlertDelivery.run_id) == r.id)).all())
        counts: dict[str, int] = {}
        for (st,) in dels:
            counts[str(st)] = counts.get(str(st), 0) + 1
        diff = (r.policy or {}).get("diff") if isinstance(r.policy, dict) else None
        out.append(
            {
                "id": r.id,
                "as_of": r.as_of,
                "created_at": r.created_at,
                "status": r.status,
                "sent_at": r.sent_at,
                "items_count": len(items_count),
                "deliveries": counts,
                "diff": diff,
            }
        )
    return {"days": days_i, "runs": out[:lim]}


@app.post("/admin/subscriber-alerts/draft")
def create_subscriber_alert_draft(payload: dict = None, session: Session = Depends(get_session)) -> dict:
    """
    Manual-only: build a DRAFT subscriber alert run (no sending).
    """

    as_of_raw = None
    if isinstance(payload, dict):
        as_of_raw = payload.get("as_of")

    as_of_dt = None
    if isinstance(as_of_raw, str) and as_of_raw.strip():
        try:
            if "T" in as_of_raw:
                as_of_dt = datetime.fromisoformat(as_of_raw)
            else:
                y, m, d = (int(x) for x in as_of_raw.split("-"))
                as_of_dt = datetime(y, m, d, 23, 59, 59)
        except Exception:
            return {"ok": False, "error": "as_of must be YYYY-MM-DD or ISO datetime"}

    run = build_draft_subscriber_alert_run_v0(session=session, as_of=as_of_dt)
    items_count = session.exec(select(AlertItem.id).where(col(AlertItem.run_id) == run.id)).all()
    diff = (run.policy or {}).get("diff") if isinstance(run.policy, dict) else None
    return {
        "ok": True,
        "run": {
            "id": run.id,
            "as_of": run.as_of,
            "created_at": run.created_at,
            "status": run.status,
            "sent_at": run.sent_at,
            "policy": run.policy,
            "source_runs": run.source_runs,
            "items_count": len(items_count),
            "diff": diff,
        },
    }


@app.post("/admin/subscriber-alerts/run/{run_id}/send")
def send_subscriber_alert_run(run_id: str, payload: dict = None, session: Session = Depends(get_session)) -> dict:
    """
    Manual-only: send a previously-built DRAFT run to active subscribers.
    """

    limit = 0
    if isinstance(payload, dict) and payload.get("limit_subscribers") is not None:
        try:
            limit = int(payload.get("limit_subscribers") or 0)
        except Exception:
            return {"ok": False, "error": "limit_subscribers must be an int"}

    try:
        res = send_subscriber_alert_run_v0(session=session, run_id=run_id, limit_subscribers=limit)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    r = session.exec(select(AlertRun).where(col(AlertRun.id) == run_id)).first()
    return {
        "ok": True,
        "result": res.__dict__,
        "run": {"id": r.id, "status": r.status, "sent_at": r.sent_at} if r else None,
    }


@app.post("/admin/subscriber-alerts/run/{run_id}/send-item")
def send_subscriber_alert_item(run_id: str, payload: dict, session: Session = Depends(get_session)) -> dict:
    """
    Manual send of a single alert item (by ticker) from a source run.
    Creates a separate run for auditability and history.
    """

    if not isinstance(payload, dict):
        return {"ok": False, "error": "Expected JSON body"}
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        return {"ok": False, "error": "Missing ticker"}

    limit = 0
    if payload.get("limit_subscribers") is not None:
        try:
            limit = int(payload.get("limit_subscribers") or 0)
        except Exception:
            return {"ok": False, "error": "limit_subscribers must be an int"}

    try:
        new_run = build_draft_subscriber_alert_run_from_tickers_v0(session=session, source_run_id=run_id, tickers=[ticker])
        res = send_subscriber_alert_run_v0(session=session, run_id=new_run.id, limit_subscribers=limit, force_send=True)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    r = session.exec(select(AlertRun).where(col(AlertRun.id) == new_run.id)).first()
    return {"ok": True, "source_run_id": run_id, "new_run_id": new_run.id, "result": res.__dict__, "run": {"id": r.id, "status": r.status, "sent_at": r.sent_at} if r else None}


@app.get("/admin/subscriber-alerts/draft/latest")
def latest_subscriber_alert_draft(auto_create: bool = True, session: Session = Depends(get_session)) -> dict:
    """
    Returns the latest draft alert_run for the current UTC day.

    If auto_create=true (default), the server will create a draft run for admin review
    when none exists for today. This keeps the "Latest" dashboard populated without
    auto-sending any emails.
    """

    today_key = datetime.utcnow().date().isoformat()

    # Prefer a draft created today (UTC). If multiple exist, pick newest.
    since = datetime.utcnow() - timedelta(days=2)
    drafts = list(
        session.exec(
            select(AlertRun)
            .where(col(AlertRun.status) == "draft")
            .where(col(AlertRun.created_at) >= since)
            .order_by(col(AlertRun.created_at).desc())
        ).all()
    )
    r = None
    for d in drafts:
        pol = d.policy or {}
        if isinstance(pol, dict) and str(pol.get("daily_key") or "") == today_key:
            r = d
            break
        if d.created_at.date().isoformat() == today_key:
            r = d
            break

    if r is None and auto_create:
        r = build_draft_subscriber_alert_run_v0(session=session)
        r.policy = dict(r.policy or {})
        r.policy["daily_key"] = today_key
        session.add(r)
        session.commit()
        session.refresh(r)

    if r is None:
        return {"ok": True, "run": None, "items": []}

    items = list(
        session.exec(select(AlertItem).where(col(AlertItem.run_id) == r.id).order_by(col(AlertItem.score).desc())).all()
    )
    return {
        "ok": True,
        "run": {"id": r.id, "as_of": r.as_of, "created_at": r.created_at, "status": r.status, "sent_at": r.sent_at, "policy": r.policy},
        "items": [x.model_dump() for x in items],
    }


@app.get("/admin/subscriber-alerts/run/{run_id}")
def get_subscriber_alert_run(run_id: str, session: Session = Depends(get_session)) -> dict:
    r = session.exec(select(AlertRun).where(col(AlertRun.id) == run_id)).first()
    if r is None:
        return {"ok": False, "error": "not found"}
    items = list(
        session.exec(select(AlertItem).where(col(AlertItem.run_id) == r.id).order_by(col(AlertItem.score).desc())).all()
    )
    deliveries = list(
        session.exec(
            select(AlertDelivery, Subscriber.email)
            .where(col(AlertDelivery.run_id) == r.id)
            .join(Subscriber, col(Subscriber.id) == col(AlertDelivery.subscriber_id))
            .order_by(col(AlertDelivery.queued_at).desc())
        ).all()
    )
    return {
        "ok": True,
        "run": {
            "id": r.id,
            "as_of": r.as_of,
            "created_at": r.created_at,
            "status": r.status,
            "sent_at": r.sent_at,
            "policy": r.policy,
            "source_runs": r.source_runs,
        },
        "items": [x.model_dump() for x in items],
        "deliveries": [{"delivery": d.model_dump(), "email": email} for (d, email) in deliveries],
    }
