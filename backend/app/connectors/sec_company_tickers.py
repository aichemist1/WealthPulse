from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from app.connectors.sec_edgar import SecEdgarClient


@dataclass(frozen=True)
class CompanyTickerRow:
    cik: str
    ticker: str
    title: Optional[str] = None


def fetch_company_tickers(client: SecEdgarClient) -> list[CompanyTickerRow]:
    """
    Fetch SEC-provided CIK<->ticker mapping.
    """

    url = "https://www.sec.gov/files/company_tickers.json"
    b = client.get(url, accept="application/json")
    data = json.loads(b.decode("utf-8", errors="replace"))

    rows: list[CompanyTickerRow] = []
    if isinstance(data, dict):
        for _, item in data.items():
            if not isinstance(item, dict):
                continue
            cik = str(item.get("cik_str") or "").strip()
            ticker = str(item.get("ticker") or "").strip().upper()
            title = item.get("title")
            if not cik or not ticker:
                continue
            rows.append(CompanyTickerRow(cik=str(int(cik)).zfill(10), ticker=ticker, title=title))
    return rows


def build_cik_to_ticker(rows: list[CompanyTickerRow]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in rows:
        out[r.cik] = r.ticker
    return out

