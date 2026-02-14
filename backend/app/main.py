from datetime import datetime

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select
from sqlmodel import col

from app.db import get_session, init_db
from app.models import (
    AdminAlert,
    Institution13FHolding,
    Institution13FReport,
    DividendMetrics,
    Security,
    Snapshot13FWhale,
    SnapshotInsiderWhale,
    SnapshotRun,
    Stock,
    SnapshotRecommendation,
)
from app.settings import settings
from app.snapshot.watchlists import compute_watchlist, parse_ticker_csv


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


@app.get("/admin/stocks")
def list_stocks(session: Session = Depends(get_session)) -> list[Stock]:
    return list(session.exec(select(Stock).order_by(Stock.ticker)).all())


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

    stmt = select(SnapshotRun).order_by(col(SnapshotRun.as_of).desc()).limit(min(limit, 200))
    if kind.strip():
        stmt = stmt.where(col(SnapshotRun.kind) == kind.strip())
    runs = list(session.exec(stmt).all())
    return {
        "runs": [{"id": r.id, "kind": r.kind, "as_of": r.as_of, "params": r.params, "created_at": r.created_at} for r in runs]
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
