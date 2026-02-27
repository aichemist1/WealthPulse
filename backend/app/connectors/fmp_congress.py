from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx


class FmpCongressError(RuntimeError):
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


@dataclass(frozen=True)
class CongressTradeRaw:
    source_id: str
    chamber: Optional[str]
    politician: str
    ticker: str
    asset_description: Optional[str]
    tx_type: Optional[str]
    amount_range: Optional[str]
    trade_date: Optional[datetime]
    filing_date: Optional[datetime]
    reported_at: Optional[datetime]
    raw: dict[str, Any]


def _pick(*vals: Any) -> Optional[str]:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def parse_fmp_disclosures(items: list[dict[str, Any]], *, chamber: str) -> list[CongressTradeRaw]:
    out: list[CongressTradeRaw] = []
    for i, r in enumerate(items or []):
        ticker = (_pick(r.get("ticker"), r.get("symbol"), r.get("security"), r.get("assetTicker")) or "").upper()
        politician = _pick(
            r.get("representative"),
            r.get("politician"),
            r.get("senator"),
            r.get("member"),
            r.get("name"),
        )
        if not ticker or not politician:
            continue

        source_id = _pick(
            r.get("transaction_id"),
            r.get("id"),
            r.get("disclosureId"),
            r.get("docId"),
            f"{chamber}:{politician}:{ticker}:{_pick(r.get('transactionDate'), r.get('tradeDate'), r.get('dateReceived'), i)}",
        ) or f"{chamber}:{i}"

        tx_type = _pick(r.get("type"), r.get("transactionType"), r.get("transaction"), r.get("ownerType"))
        amount_range = _pick(r.get("amount"), r.get("amount_range"), r.get("amountRange"), r.get("range"))
        trade_date = _parse_dt(_pick(r.get("transactionDate"), r.get("tradeDate"), r.get("transaction_date")))
        filing_date = _parse_dt(_pick(r.get("disclosureDate"), r.get("filedDate"), r.get("filingDate"), r.get("dateReceived")))
        reported_at = _parse_dt(_pick(r.get("dateReceived"), r.get("created"), r.get("reportedDate")))
        asset_desc = _pick(r.get("assetDescription"), r.get("asset"), r.get("description"), r.get("securityDescription"))

        out.append(
            CongressTradeRaw(
                source_id=str(source_id),
                chamber=chamber,
                politician=str(politician),
                ticker=ticker,
                asset_description=asset_desc,
                tx_type=tx_type.lower() if tx_type else None,
                amount_range=amount_range,
                trade_date=trade_date,
                filing_date=filing_date,
                reported_at=reported_at,
                raw=r,
            )
        )
    return out


@dataclass
class FmpCongressClient:
    api_key: str
    timeout_s: float = 20.0
    base_url: str = "https://financialmodelingprep.com/stable"

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
        p = dict(params or {})
        p["apikey"] = self.api_key
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        try:
            resp = httpx.get(url, params=p, timeout=self.timeout_s, headers={"Accept": "application/json"})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise FmpCongressError(f"FMP request failed: {e}") from e
        try:
            payload = resp.json()
        except Exception as e:
            raise FmpCongressError(f"FMP returned invalid JSON: {e}") from e
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return [x for x in payload["data"] if isinstance(x, dict)]
        return []

    def fetch_house(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._get("/house-disclosure", {"limit": max(1, min(int(limit), 500))})

    def fetch_senate(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._get("/senate-disclosure", {"limit": max(1, min(int(limit), 500))})
