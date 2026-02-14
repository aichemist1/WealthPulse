from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional

from app.models import InsiderTx


@dataclass(frozen=True)
class InsiderWhaleRow:
    ticker: str
    total_purchase_value: float
    purchase_tx_count: int
    latest_event_date: Optional[datetime]


def compute_insider_whales(
    *,
    rows: Iterable[InsiderTx],
    min_value: float,
) -> list[InsiderWhaleRow]:
    """
    Aggregate large *purchase* transactions by ticker.

    Intended as a v0 "whale buys" proxy:
    - only transaction_code == "P"
    - excludes derivative transactions
    - only includes rows with transaction_value >= min_value
    """
    agg: dict[str, InsiderWhaleRow] = {}
    for r in rows:
        if r.is_derivative:
            continue
        if (r.transaction_code or "").upper() != "P":
            continue
        if r.transaction_value is None or r.transaction_value < min_value:
            continue

        cur = agg.get(r.ticker)
        latest = r.event_date if r.event_date else None
        if cur is None:
            agg[r.ticker] = InsiderWhaleRow(
                ticker=r.ticker,
                total_purchase_value=float(r.transaction_value),
                purchase_tx_count=1,
                latest_event_date=latest,
            )
        else:
            new_latest = cur.latest_event_date
            if latest and (new_latest is None or latest > new_latest):
                new_latest = latest
            agg[r.ticker] = InsiderWhaleRow(
                ticker=cur.ticker,
                total_purchase_value=cur.total_purchase_value + float(r.transaction_value),
                purchase_tx_count=cur.purchase_tx_count + 1,
                latest_event_date=new_latest,
            )

    return sorted(agg.values(), key=lambda x: x.total_purchase_value, reverse=True)


def window_start(as_of: datetime, days: int) -> datetime:
    if days <= 0:
        return as_of
    return as_of - timedelta(days=days)
