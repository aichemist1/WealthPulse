from app.snapshot.trend import compute_trend_from_closes


def test_compute_trend_from_closes_bullish():
    dates = [f"2026-01-{i:02d}" for i in range(1, 61)]
    closes = [float(i) for i in range(1, 61)]
    tm = compute_trend_from_closes(dates=dates, closes=closes)
    assert tm.sma50 is not None
    assert tm.return_20d is not None
    assert tm.bullish is True

