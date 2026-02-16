from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

from app.models import SnapshotRecommendation, SnapshotRun
from app.snapshot.daily_artifact_v0 import build_daily_snapshot_payload_v0


def _mk_run(session: Session, *, kind: str, as_of: datetime) -> SnapshotRun:
    run = SnapshotRun(kind=kind, as_of=as_of, params={"k": kind})
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def test_daily_artifact_payload_has_source_runs_and_stable_hash() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    as_of = datetime(2025, 11, 15, 23, 59, 59)

    with Session(engine) as session:
        rec_run = _mk_run(session, kind="recommendations_v0", as_of=as_of)
        fresh_run = _mk_run(session, kind="fresh_signals_v0", as_of=as_of)

        session.add(
            SnapshotRecommendation(
                run_id=rec_run.id,
                ticker="AAPL",
                segment="Institutional Accumulation (13F)",
                action="watch",
                direction="bullish",
                score=72,
                confidence=0.35,
                reasons={"delta_value_usd": 1000, "breadth": {"increase": 1, "total": 1}},
            )
        )
        session.add(
            SnapshotRecommendation(
                run_id=fresh_run.id,
                ticker="TSLA",
                segment="Fresh Whale Signals (SC13 + Insider + Trend)",
                action="watch",
                direction="bullish",
                score=66,
                confidence=0.42,
                reasons={"insider": {"buy_value": 100_000, "sell_value": 10_000}, "trend_flags": {"bullish_recent": True}},
            )
        )
        session.commit()

        p1, h1, src1 = build_daily_snapshot_payload_v0(session=session, as_of=as_of, version="v0.1")
        p2, h2, src2 = build_daily_snapshot_payload_v0(session=session, as_of=as_of, version="v0.1")

        assert h1 == h2
        assert src1 == src2
        assert p1["source_runs"]["recommendations_v0"]["id"] == rec_run.id
        assert p1["source_runs"]["fresh_signals_v0"]["id"] == fresh_run.id
