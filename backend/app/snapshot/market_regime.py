from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models import PriceBar
from app.snapshot.trend import compute_trend_from_closes


def compute_market_regime(
    *,
    session: Session,
    as_of: datetime,
    ticker: str = "SPY",
) -> Optional[dict]:
    """
    Best-effort market regime corroborator (v0):
    - Uses the same trend rule as tickers: close>SMA50 and 20D return>0
    - "recent" if last bar is within 3 calendar days of as_of

    Returns a dict suitable for embedding into `reasons`, or None if data missing.
    """

    as_of_day = as_of.date().isoformat()
    bars = list(
        session.exec(
            select(PriceBar.date, PriceBar.close)
            .where(PriceBar.ticker == ticker, PriceBar.source == "stooq", PriceBar.date <= as_of_day)
            .order_by(PriceBar.date)
        ).all()
    )
    if len(bars) < 55:
        return None

    dates = [d for (d, _) in bars]
    closes = [float(c) for (_, c) in bars]
    tm = compute_trend_from_closes(dates=dates, closes=closes)

    is_recent = False
    if tm.as_of_date:
        try:
            y, m, d = (int(x) for x in tm.as_of_date.split("-"))
            last_day = datetime(y, m, d).date()
            delta_days = (as_of.date() - last_day).days
            is_recent = 0 <= delta_days <= 3
        except Exception:
            is_recent = False

    bullish_recent = bool(is_recent and tm.bullish)
    bearish_recent = bool(
        is_recent
        and (tm.sma50 is not None and tm.return_20d is not None and tm.close is not None)
        and (tm.close < tm.sma50 and tm.return_20d < 0)
    )

    return {
        "ticker": ticker,
        "as_of_date": tm.as_of_date,
        "close": tm.close,
        "sma50": tm.sma50,
        "return_20d": tm.return_20d,
        "bullish_recent": bullish_recent,
        "bearish_recent": bearish_recent,
        "recent": is_recent,
        "rule": "bullish if close>SMA50 and 20D return>0",
    }

