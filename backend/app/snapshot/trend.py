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

