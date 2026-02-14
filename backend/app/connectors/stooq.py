from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx


@dataclass(frozen=True)
class StooqDailyBar:
    day: date
    close: float
    volume: Optional[int]


def stooq_symbol_for_ticker(ticker: str) -> str:
    t = ticker.strip().lower()
    if not t:
        return t
    # Stooq uses ".us" suffix for US equities.
    if "." in t:
        return t
    return f"{t}.us"


def fetch_daily_csv(ticker: str, *, timeout_s: float = 30.0) -> str:
    sym = stooq_symbol_for_ticker(ticker)
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    resp = httpx.get(url, timeout=timeout_s, headers={"Accept": "text/csv"})
    resp.raise_for_status()
    return resp.text


def parse_daily_csv(csv_text: str) -> list[StooqDailyBar]:
    """
    Parse Stooq daily CSV:
      Date,Open,High,Low,Close,Volume
    """

    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = [h.strip().lower() for h in lines[0].split(",")]
    if "date" not in header or "close" not in header:
        return []

    idx_date = header.index("date")
    idx_close = header.index("close")
    idx_vol = header.index("volume") if "volume" in header else -1

    out: list[StooqDailyBar] = []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) <= max(idx_date, idx_close, idx_vol):
            continue
        try:
            y, m, d = (int(x) for x in parts[idx_date].split("-"))
            day = date(y, m, d)
            close = float(parts[idx_close])
        except Exception:
            continue
        vol = None
        if idx_vol >= 0:
            try:
                vol = int(float(parts[idx_vol]))
            except Exception:
                vol = None
        out.append(StooqDailyBar(day=day, close=close, volume=vol))

    return sorted(out, key=lambda b: b.day)

