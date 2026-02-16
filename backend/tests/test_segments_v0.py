from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

from app.models import SnapshotRecommendation, SnapshotRun
from app.snapshot.segments_v0 import compute_segments_v0


def _mk_run(session: Session, *, kind: str) -> SnapshotRun:
    run = SnapshotRun(kind=kind, as_of=datetime(2025, 11, 15, 0, 0, 0), params={})
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def test_segments_primary_selection_prefers_risk_when_materially_stronger() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        fresh = _mk_run(session, kind="fresh_signals_v0")
        session.add(
            SnapshotRecommendation(
                run_id=fresh.id,
                ticker="MU",
                segment="Fresh Whale Signals (SC13 + Insider + Trend)",
                action="avoid",
                direction="bearish",
                score=55,
                confidence=0.5,
                reasons={
                    "insider": {"buy_value": 10_000, "sell_value": 2_000_000, "net_value": -1_990_000},
                    "trend_flags": {"bullish_recent": True, "bearish_recent": False},
                    "trend": {"return_20d": 0.12},
                    "divergence": {"type": "bearish_divergence"},
                },
            )
        )
        session.commit()

        out = compute_segments_v0(session=session, picks_per_segment=2)
        risk = next(s for s in out["segments"] if s["key"] == "risk")
        tickers = {p["ticker"] for p in risk["picks"]}
        assert "MU" in tickers


def test_segments_primary_selection_uses_institutional_when_strongest() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        rec = _mk_run(session, kind="recommendations_v0")
        session.add(
            SnapshotRecommendation(
                run_id=rec.id,
                ticker="AAPL",
                segment="Institutional Accumulation (13F)",
                action="watch",
                direction="bullish",
                score=72,
                confidence=0.35,
                reasons={
                    "delta_value_usd": 6_000_000_000,
                    "breadth": {"increase": 7, "total": 8},
                    "corroborators": {"trend_bullish_recent": True},
                    "trend_adjustment": 2,
                },
            )
        )
        session.commit()

        out = compute_segments_v0(session=session, picks_per_segment=2)
        institutional = next(s for s in out["segments"] if s["key"] == "institutional")
        tickers = {p["ticker"] for p in institutional["picks"]}
        assert "AAPL" in tickers
