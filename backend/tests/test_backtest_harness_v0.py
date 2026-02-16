from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

from app.backtest.harness_v0 import run_backtest_v0
from app.models import PriceBar, SnapshotRecommendation, SnapshotRun


def _mk_run(session: Session, *, kind: str, as_of: datetime) -> SnapshotRun:
    run = SnapshotRun(kind=kind, as_of=as_of, params={})
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _add_bars(session: Session, ticker: str, closes: list[float], start_day: datetime) -> None:
    for i, c in enumerate(closes):
        d = (start_day + timedelta(days=i)).date().isoformat()
        session.add(PriceBar(ticker=ticker, date=d, close=float(c), volume=1000, source="stooq"))


def test_backtest_harness_buy_and_avoid_vs_baseline() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    start_day = datetime(2025, 11, 1, 0, 0, 0)
    as_of = datetime(2025, 11, 1, 23, 59, 59)

    with Session(engine) as session:
        run = _mk_run(session, kind="fresh_signals_v0", as_of=as_of)
        session.add(
            SnapshotRecommendation(
                run_id=run.id,
                ticker="AAPL",
                segment="Fresh Whale Signals (SC13 + Insider + Trend)",
                action="buy",
                direction="bullish",
                score=80,
                confidence=0.5,
                reasons={},
            )
        )
        session.add(
            SnapshotRecommendation(
                run_id=run.id,
                ticker="MU",
                segment="Fresh Whale Signals (SC13 + Insider + Trend)",
                action="avoid",
                direction="bearish",
                score=30,
                confidence=0.5,
                reasons={},
            )
        )

        _add_bars(session, "AAPL", [100, 102, 104], start_day)
        _add_bars(session, "MU", [100, 98, 95], start_day)
        _add_bars(session, "SPY", [100, 101, 102], start_day)
        session.commit()

        out = run_backtest_v0(
            session=session,
            start_as_of=datetime(2025, 11, 1, 0, 0, 0),
            end_as_of=datetime(2025, 11, 2, 23, 59, 59),
            source_kinds=["fresh_signals_v0"],
            baseline_ticker="SPY",
            horizons=[2],
            top_n_per_action=5,
        )

    metrics = {(m["source_kind"], m["action"], m["horizon_days"]): m for m in out["metrics"]}
    buy = metrics[("fresh_signals_v0", "buy", 2)]
    avoid = metrics[("fresh_signals_v0", "avoid", 2)]

    assert buy["evaluated"] == 1
    assert buy["hit_rate_vs_baseline"] == 1.0
    assert buy["avg_excess_return"] > 0

    assert avoid["evaluated"] == 1
    assert avoid["hit_rate_vs_baseline"] == 1.0
    assert avoid["avg_excess_return"] > 0
