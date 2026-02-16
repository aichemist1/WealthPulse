from datetime import datetime

from app.snapshot.fresh_signals_v0 import FreshSignalFeatures, FreshSignalParams, score_fresh_signal_v0


def test_fresh_signal_buy_when_sc13_insider_and_bullish_trend() -> None:
    params = FreshSignalParams(as_of=datetime(2026, 2, 11, 23, 59, 59))
    row = score_fresh_signal_v0(
        features=FreshSignalFeatures(
            ticker="XYZ",
            sc13_count=1,
            sc13_latest_filed_at="2026-02-10T00:00:00",
            insider_buy_value=50_000_000.0,
            insider_sell_value=0.0,
            insider_buy_count=1,
            insider_sell_count=0,
            insider_latest_event_date="2026-02-10T00:00:00",
            trend={"as_of_date": "2026-02-11", "close": 100.0, "sma50": 90.0, "return_20d": 0.10, "bullish": True},
            trend_bullish_recent=True,
            trend_bearish_recent=False,
            volume={"avg20": 10_000_000.0, "latest": 25_000_000.0, "ratio": 2.5, "spike": True},
            volume_spike=True,
            context_13f=None,
            market=None,
            sector=None,
        ),
        params=params,
    )
    assert row.action == "buy"
    assert row.direction == "bullish"
    assert row.score >= params.buy_score_threshold
    assert row.confidence > 0.5


def test_fresh_signal_avoid_when_big_sell_and_bearish_trend() -> None:
    params = FreshSignalParams(as_of=datetime(2026, 2, 11, 23, 59, 59))
    row = score_fresh_signal_v0(
        features=FreshSignalFeatures(
            ticker="ABC",
            sc13_count=0,
            sc13_latest_filed_at=None,
            insider_buy_value=0.0,
            insider_sell_value=50_000_000.0,
            insider_buy_count=0,
            insider_sell_count=1,
            insider_latest_event_date="2026-02-10T00:00:00",
            trend={"as_of_date": "2026-02-11", "close": 80.0, "sma50": 90.0, "return_20d": -0.10, "bullish": False},
            trend_bullish_recent=False,
            trend_bearish_recent=True,
            volume=None,
            volume_spike=False,
            context_13f=None,
            market=None,
            sector=None,
        ),
        params=params,
    )
    assert row.action == "avoid"
    assert row.direction == "bearish"
    assert row.score <= params.avoid_score_threshold


def test_fresh_signal_social_persistent_spike_adjusts_score() -> None:
    params = FreshSignalParams(as_of=datetime(2026, 2, 11, 23, 59, 59))
    row = score_fresh_signal_v0(
        features=FreshSignalFeatures(
            ticker="SOC",
            sc13_count=0,
            sc13_latest_filed_at=None,
            insider_buy_value=0.0,
            insider_sell_value=0.0,
            insider_buy_count=0,
            insider_sell_count=0,
            insider_latest_event_date=None,
            trend=None,
            trend_bullish_recent=False,
            trend_bearish_recent=False,
            volume=None,
            volume_spike=False,
            context_13f=None,
            market=None,
            sector=None,
            social={
                "enabled": True,
                "mentions_latest": 20,
                "mentions_baseline_7d": 6.0,
                "velocity": 3.33,
                "persistent": True,
                "sentiment_hint": 0.4,
                "velocity_threshold": 1.5,
                "min_mentions": 5,
            },
        ),
        params=params,
    )
    assert row.score >= 54
    assert float((row.reasons.get("social_adjustment") or {}).get("score") or 0.0) >= 4.0
