from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models import PriceBar


@dataclass(frozen=True)
class WatchlistRow:
    ticker: str
    as_of_date: Optional[str]
    close: Optional[float]
    sma50: Optional[float]
    sma200: Optional[float]
    return_20d: Optional[float]
    return_60d: Optional[float]
    bullish_recent: Optional[bool]
    bearish_recent: Optional[bool]
    volume: Optional[int]
    volume_avg20: Optional[float]
    volume_ratio: Optional[float]


def parse_ticker_csv(value: str) -> list[str]:
    out: list[str] = []
    for part in (value or "").replace("\n", ",").split(","):
        t = part.strip().upper()
        if not t:
            continue
        out.append(t)
    # stable unique
    seen: set[str] = set()
    uniq: list[str] = []
    for t in out:
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    return uniq


def _sma(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _compute_watchlist_row(ticker: str, dates: list[str], closes: list[float], volumes: list[Optional[int]]) -> WatchlistRow:
    if not dates or not closes or len(dates) != len(closes):
        return WatchlistRow(
            ticker=ticker,
            as_of_date=None,
            close=None,
            sma50=None,
            sma200=None,
            return_20d=None,
            return_60d=None,
            bullish_recent=None,
            bearish_recent=None,
            volume=None,
            volume_avg20=None,
            volume_ratio=None,
        )

    close = closes[-1]
    as_of_date = dates[-1]
    sma50 = _sma(closes[-50:]) if len(closes) >= 50 else None
    sma200 = _sma(closes[-200:]) if len(closes) >= 200 else None

    ret20 = None
    if len(closes) >= 21:
        prev = closes[-21]
        if prev:
            ret20 = (close / prev) - 1.0

    ret60 = None
    if len(closes) >= 61:
        prev = closes[-61]
        if prev:
            ret60 = (close / prev) - 1.0

    bullish = None
    bearish = None
    if sma50 is not None and ret20 is not None:
        bullish = close > sma50 and ret20 > 0
        bearish = close < sma50 and ret20 < 0

    vol_latest = volumes[-1] if volumes else None
    vol_avg20 = None
    vol_ratio = None
    vols = [float(v) for v in volumes if v is not None]
    if len(vols) >= 21:
        vol_avg20 = sum(vols[-21:-1]) / 20.0
        if vol_avg20:
            vol_ratio = (float(vol_latest) / vol_avg20) if vol_latest is not None else None

    return WatchlistRow(
        ticker=ticker,
        as_of_date=as_of_date,
        close=close,
        sma50=sma50,
        sma200=sma200,
        return_20d=ret20,
        return_60d=ret60,
        bullish_recent=bullish,
        bearish_recent=bearish,
        volume=vol_latest,
        volume_avg20=vol_avg20,
        volume_ratio=vol_ratio,
    )


def compute_watchlist(
    *,
    session: Session,
    tickers: list[str],
    as_of: Optional[datetime] = None,
    keep_last_days: int = 260,
) -> list[WatchlistRow]:
    as_of_day = (as_of or datetime.utcnow()).date().isoformat()
    out: list[WatchlistRow] = []
    for t in [x.strip().upper() for x in tickers if x.strip()]:
        rows = list(
            session.exec(
                select(PriceBar.date, PriceBar.close, PriceBar.volume)
                .where(PriceBar.ticker == t, PriceBar.source == "stooq", PriceBar.date <= as_of_day)
                .order_by(PriceBar.date)
            ).all()
        )
        if keep_last_days > 0 and len(rows) > keep_last_days:
            rows = rows[-keep_last_days:]
        dates = [d for (d, _, _) in rows]
        closes = [float(c) for (_, c, _) in rows]
        vols = [v for (_, _, v) in rows]
        out.append(_compute_watchlist_row(t, dates, closes, vols))
    return out

