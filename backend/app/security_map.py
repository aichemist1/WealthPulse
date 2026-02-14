from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SecurityMapRow:
    cusip: str
    ticker: str
    name: Optional[str] = None
    cik: Optional[str] = None


def parse_security_map_csv(text: str) -> list[SecurityMapRow]:
    """
    Parse a simple CSV with header containing at least: cusip,ticker
    Optional columns: name,cik

    Notes:
    - This is a minimal parser (comma-splitting; no quoted-field support).
    """

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    header = [h.strip().lower() for h in lines[0].split(",")]
    if "cusip" not in header or "ticker" not in header:
        raise ValueError("CSV must have header with at least cusip,ticker")

    idx_cusip = header.index("cusip")
    idx_ticker = header.index("ticker")
    idx_name = header.index("name") if "name" in header else -1
    idx_cik = header.index("cik") if "cik" in header else -1

    rows: list[SecurityMapRow] = []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) <= max(idx_cusip, idx_ticker, idx_name, idx_cik):
            continue
        cusip = parts[idx_cusip].upper()
        ticker = parts[idx_ticker].upper()
        if not cusip or not ticker:
            continue
        name = parts[idx_name] if idx_name >= 0 and parts[idx_name] else None
        cik = parts[idx_cik] if idx_cik >= 0 and parts[idx_cik] else None
        rows.append(SecurityMapRow(cusip=cusip, ticker=ticker, name=name, cik=cik))

    return rows

