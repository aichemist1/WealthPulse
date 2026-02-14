from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlmodel import Session, select

from app.connectors.stooq import fetch_daily_csv, parse_daily_csv
from app.models import PriceBar


@dataclass(frozen=True)
class IngestPricesResult:
    tickers_seen: int
    bars_inserted: int


def ingest_stooq_prices(
    *,
    session: Session,
    tickers: list[str],
    keep_last_days: int = 200,
) -> IngestPricesResult:
    inserted = 0
    for t in [x.strip().upper() for x in tickers if x.strip()]:
        try:
            csv_text = fetch_daily_csv(t)
        except httpx.HTTPError:
            continue
        bars = parse_daily_csv(csv_text)
        if keep_last_days > 0:
            bars = bars[-keep_last_days:]
        now = datetime.utcnow()

        for b in bars:
            day_s = b.day.isoformat()
            exists = session.exec(
                select(PriceBar.id).where(PriceBar.ticker == t, PriceBar.date == day_s, PriceBar.source == "stooq")
            ).first()
            if exists is not None:
                continue
            session.add(
                PriceBar(
                    ticker=t,
                    date=day_s,
                    close=float(b.close),
                    volume=b.volume,
                    source="stooq",
                    detected_at=now,
                )
            )
            inserted += 1
        session.commit()

    return IngestPricesResult(tickers_seen=len(tickers), bars_inserted=inserted)

