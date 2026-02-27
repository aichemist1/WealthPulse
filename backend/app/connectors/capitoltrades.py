from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Any, Optional

import httpx


class CapitolTradesError(RuntimeError):
    pass


def _parse_dt(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    for x in (s, s.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(x).replace(tzinfo=None)
        except Exception:
            pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def _pick(*vals: Any) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


@dataclass(frozen=True)
class CongressTradeRaw:
    source_id: str
    chamber: Optional[str]
    politician: str
    ticker: str
    tx_type: Optional[str]
    amount_range: Optional[str]
    trade_date: Optional[datetime]
    filing_date: Optional[datetime]
    reported_at: Optional[datetime]
    raw: dict[str, Any]


def _from_candidate(candidate: dict[str, Any], *, salt: str = "") -> Optional[CongressTradeRaw]:
    ticker = (_pick(candidate.get("ticker"), candidate.get("symbol"), candidate.get("assetTicker")) or "").upper()
    politician = _pick(
        candidate.get("representative"),
        candidate.get("politician"),
        candidate.get("senator"),
        candidate.get("member"),
        candidate.get("name"),
    )
    if not ticker or not politician:
        return None

    tx_type = _pick(candidate.get("txType"), candidate.get("type"), candidate.get("transactionType"), candidate.get("transaction"))
    amount_range = _pick(candidate.get("amount"), candidate.get("amountRange"), candidate.get("amount_range"), candidate.get("range"))
    trade_date = _parse_dt(_pick(candidate.get("tradeDate"), candidate.get("transactionDate"), candidate.get("traded")))
    filing_date = _parse_dt(_pick(candidate.get("filingDate"), candidate.get("disclosureDate"), candidate.get("filed"), candidate.get("filedAt")))
    reported_at = _parse_dt(_pick(candidate.get("reportedAt"), candidate.get("dateReceived"), candidate.get("created")))
    chamber = _pick(candidate.get("chamber"))
    source_id = _pick(candidate.get("transaction_id"), candidate.get("id"), candidate.get("slug"))
    if not source_id:
        key = f"{salt}|{politician}|{ticker}|{tx_type}|{trade_date}|{filing_date}|{amount_range}"
        source_id = "ct_" + sha1(key.encode("utf-8")).hexdigest()[:20]

    return CongressTradeRaw(
        source_id=str(source_id),
        chamber=(str(chamber).lower() if chamber else None),
        politician=str(politician),
        ticker=ticker,
        tx_type=(str(tx_type).lower() if tx_type else None),
        amount_range=amount_range,
        trade_date=trade_date,
        filing_date=filing_date,
        reported_at=reported_at,
        raw=candidate,
    )


def _walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_dicts(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_dicts(it)


def parse_capitoltrades_html(html: str) -> list[CongressTradeRaw]:
    out: list[CongressTradeRaw] = []

    # Strategy 1: Next.js bootstrap JSON.
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S | re.I)
    if m:
        try:
            payload = json.loads(m.group(1))
            for d in _walk_dicts(payload):
                if not isinstance(d, dict):
                    continue
                if not _pick(d.get("ticker"), d.get("symbol"), d.get("assetTicker")):
                    continue
                if not _pick(d.get("representative"), d.get("politician"), d.get("senator"), d.get("member"), d.get("name")):
                    continue
                rec = _from_candidate(d, salt="next_data")
                if rec is not None:
                    out.append(rec)
        except Exception:
            pass

    # Strategy 2: human-readable line parse fallback.
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    pattern = re.compile(
        r"(?:Democratic|Republican|Independent)?\s*"
        r"(?P<name>[A-Z][A-Za-z\.\-'\s]{2,80}?)\s+traded\s+"
        r"(?P<ticker>[A-Z]{1,6}(?:\.[A-Z])?)\s+\((?P<tx>Purchase|Sale)\)\s*-\s*"
        r"(?P<amount>\$[0-9,]+(?:\s*-\s*\$[0-9,]+)?)\s*Filed\s+"
        r"(?P<filed>\d{4}-\d{2}-\d{2})\s*Traded\s+(?P<traded>\d{4}-\d{2}-\d{2})",
        flags=re.I,
    )
    for i, mm in enumerate(pattern.finditer(text)):
        d = {
            "politician": mm.group("name").strip(),
            "ticker": mm.group("ticker").upper(),
            "transactionType": mm.group("tx"),
            "amount_range": mm.group("amount"),
            "filingDate": mm.group("filed"),
            "tradeDate": mm.group("traded"),
            "id": f"regex_{i}_{mm.group('ticker')}_{mm.group('filed')}",
            "chamber": None,
        }
        rec = _from_candidate(d, salt="regex")
        if rec is not None:
            out.append(rec)

    dedup: dict[tuple[str, str], CongressTradeRaw] = {}
    for r in out:
        key = (r.source_id, r.ticker)
        dedup[key] = r
    return list(dedup.values())


@dataclass
class CapitolTradesClient:
    timeout_s: float = 20.0
    base_url: str = "https://www.capitoltrades.com"

    def fetch_trades_page(self, *, page: int = 1, page_size: int = 96) -> str:
        p = max(1, int(page))
        s = max(10, min(int(page_size), 200))
        url = f"{self.base_url.rstrip('/')}/trades"
        try:
            resp = httpx.get(
                url,
                params={"page": p, "pageSize": s},
                timeout=self.timeout_s,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "WealthPulse/0.1 (+capitoltrades-ingest)",
                },
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise CapitolTradesError(f"CapitolTrades request failed: {e}") from e
        return resp.text
