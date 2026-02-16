from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class TrendMetrics:
    as_of_date: Optional[str]
    close: Optional[float]
    sma50: Optional[float]
    return_20d: Optional[float]
    bullish: bool


def _sma(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def compute_trend_from_closes(
    *,
    dates: list[str],
    closes: list[float],
) -> TrendMetrics:
    """
    Simple, explainable trend corroborator:
    - bullish if close > SMA50 AND 20D return > 0
    """

    if not dates or not closes or len(dates) != len(closes):
        return TrendMetrics(as_of_date=None, close=None, sma50=None, return_20d=None, bullish=False)

    as_of_date = dates[-1]
    close = closes[-1]

    sma50 = _sma(closes[-50:]) if len(closes) >= 50 else None
    ret20 = None
    if len(closes) >= 21:
        prev = closes[-21]
        if prev:
            ret20 = (close / prev) - 1.0

    bullish = False
    if sma50 is not None and ret20 is not None:
        bullish = close > sma50 and ret20 > 0

    return TrendMetrics(as_of_date=as_of_date, close=close, sma50=sma50, return_20d=ret20, bullish=bullish)


def compute_technical_snapshot_from_closes(*, dates: list[str], closes: list[float]) -> dict:
    """
    Compute a lightweight technical snapshot for UI + scoring guardrails.

    This is intentionally simple and explainable:
    - SMA50/SMA200
    - 20D/60D return
    - 60D high/low proximity
    - derived flags (bullish/bearish, extended, near support/resistance)
    """
    tm = compute_trend_from_closes(dates=dates, closes=closes)
    as_of_date = tm.as_of_date
    close = tm.close
    sma50 = tm.sma50
    ret20 = tm.return_20d

    ret60 = None
    if len(closes) >= 61 and closes[-61]:
        ret60 = (closes[-1] / closes[-61]) - 1.0

    sma200 = None
    if len(closes) >= 200:
        sma200 = sum(closes[-200:]) / 200.0

    high60 = None
    low60 = None
    if len(closes) >= 60:
        window = closes[-60:]
        high60 = max(window) if window else None
        low60 = min(window) if window else None

    def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None or b is None or b == 0:
            return None
        return (a / b) - 1.0

    dist_sma50 = _pct(close, sma50)
    dist_sma200 = _pct(close, sma200)
    dist_high60 = _pct(close, high60)
    dist_low60 = _pct(close, low60)

    bullish = bool(close is not None and sma50 is not None and ret20 is not None and close > sma50 and ret20 > 0)
    bearish = bool(close is not None and sma50 is not None and ret20 is not None and close < sma50 and ret20 < 0)

    near_sma50 = bool(dist_sma50 is not None and abs(dist_sma50) <= 0.02)
    near_support = bool(bullish and close is not None and sma50 is not None and close >= sma50 and near_sma50)

    # "Resistance" approximation: close near the 60D high. (No intraday data; keep it cheap.)
    near_resistance_60d = bool(bullish and dist_high60 is not None and dist_high60 >= -0.02)

    extended_up = bool(bullish and dist_sma50 is not None and dist_sma50 >= 0.08)
    below_sma200 = bool(sma200 is not None and close is not None and close < sma200)

    return {
        "as_of_date": as_of_date,
        "close": close,
        "sma50": sma50,
        "sma200": sma200,
        "return_20d": ret20,
        "return_60d": ret60,
        "high_60d": high60,
        "low_60d": low60,
        "dist_sma50_pct": dist_sma50,
        "dist_sma200_pct": dist_sma200,
        "dist_high_60d_pct": dist_high60,
        "dist_low_60d_pct": dist_low60,
        "bullish": bullish,
        "bearish": bearish,
        "near_support": near_support,
        "near_resistance_60d": near_resistance_60d,
        "extended_up": extended_up,
        "below_sma200": below_sma200,
    }
