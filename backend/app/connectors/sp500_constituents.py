from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sp500Constituent:
    ticker: str
    name: str | None = None


def parse_sp500_constituents_csv(csv_text: str) -> list[Sp500Constituent]:
    """
    Parse a constituents CSV into tickers.

    Expected header includes a ticker column named one of:
    - Symbol
    - symbol
    - Ticker
    - ticker

    This is intentionally a minimal CSV parser (comma-splitting; no quoted fields).
    """

    lines = [ln.strip() for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        return []

    header = [h.strip() for h in lines[0].split(",")]
    ticker_idx = None
    name_idx = None
    for i, h in enumerate(header):
        hl = h.lower()
        if hl in {"symbol", "ticker"}:
            ticker_idx = i
        if hl in {"name", "security"}:
            name_idx = i

    if ticker_idx is None:
        raise ValueError("CSV must contain a Symbol/Ticker column")

    out: list[Sp500Constituent] = []
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) <= ticker_idx:
            continue
        t = parts[ticker_idx].strip().upper()
        if not t:
            continue
        name = parts[name_idx].strip() if (name_idx is not None and len(parts) > name_idx and parts[name_idx]) else None
        out.append(Sp500Constituent(ticker=t, name=name))
    return out

