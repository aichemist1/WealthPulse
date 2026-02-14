from app.models import SnapshotRecommendation
from app.snapshot.alerts_v0 import new_action_tickers


def _rec(ticker: str, action: str) -> SnapshotRecommendation:
    return SnapshotRecommendation(
        run_id="x",
        ticker=ticker,
        segment="seg",
        action=action,
        direction="neutral",
        score=50,
        confidence=0.3,
        reasons={},
    )


def test_new_action_tickers_detects_new_buys() -> None:
    prev = [_rec("AAA", "watch"), _rec("BBB", "buy")]
    cur = [_rec("AAA", "buy"), _rec("BBB", "buy"), _rec("CCC", "watch")]
    assert new_action_tickers(cur_rows=cur, prev_rows=prev, action="buy") == {"AAA"}


def test_new_action_tickers_detects_new_avoids() -> None:
    prev = [_rec("AAA", "avoid")]
    cur = [_rec("AAA", "avoid"), _rec("BBB", "avoid")]
    assert new_action_tickers(cur_rows=cur, prev_rows=prev, action="avoid") == {"BBB"}

