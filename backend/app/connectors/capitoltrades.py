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

    # Strategy 3: Next.js App Router payload heuristics (escaped JSON fragments).
    # Some pages no longer expose __NEXT_DATA__; they embed serialized chunks where keys
    # appear as \"ticker\":\"XYZ\" etc.
    unescaped = html.replace('\\"', '"')
    ticker_iter = list(re.finditer(r'"ticker"\s*:\s*"(?P<t>[A-Z]{1,6}(?:\.[A-Z])?)"', unescaped))
    for i, m_t in enumerate(ticker_iter):
        left = max(0, m_t.start() - 700)
        right = min(len(unescaped), m_t.end() + 700)
        window = unescaped[left:right]

        pol_m = re.search(
            r'"(?:representative|politician|senator|member|name)"\s*:\s*"(?P<v>[^"]{3,120})"',
            window,
            flags=re.I,
        )
        if not pol_m:
            continue

        tx_m = re.search(r'"(?:txType|transactionType|type|transaction)"\s*:\s*"(?P<v>[^"]{1,40})"', window, flags=re.I)
        amt_m = re.search(r'"(?:amountRange|amount_range|amount|range)"\s*:\s*"(?P<v>[^"]{1,80})"', window, flags=re.I)
        trd_m = re.search(r'"(?:tradeDate|traded|transactionDate)"\s*:\s*"(?P<v>\d{4}-\d{2}-\d{2}[^"]*)"', window, flags=re.I)
        fil_m = re.search(r'"(?:filingDate|filed|disclosureDate|publishedAt)"\s*:\s*"(?P<v>\d{4}-\d{2}-\d{2}[^"]*)"', window, flags=re.I)
        id_m = re.search(r'"(?:transaction_id|id|slug)"\s*:\s*"(?P<v>[^"]{2,120})"', window, flags=re.I)
        chamber_m = re.search(r'"chamber"\s*:\s*"(?P<v>house|senate)"', window, flags=re.I)

        if not tx_m and not trd_m and not fil_m:
            # avoid random ticker+name joins from unrelated script chunks.
            continue

        d = {
            "id": id_m.group("v") if id_m else f"heur_{i}_{m_t.group('t')}",
            "ticker": m_t.group("t"),
            "politician": pol_m.group("v").strip(),
            "transactionType": tx_m.group("v").strip() if tx_m else None,
            "amount_range": amt_m.group("v").strip() if amt_m else None,
            "tradeDate": trd_m.group("v").strip() if trd_m else None,
            "filingDate": fil_m.group("v").strip() if fil_m else None,
            "chamber": chamber_m.group("v").strip().lower() if chamber_m else None,
        }
        rec = _from_candidate(d, salt="heuristic")
        if rec is not None:
            out.append(rec)

    # Strategy 4: parse rendered HTML table/cards directly.
    # Observed shape on /trades includes:
    # - issuer ticker: <span class="q-field issuer-ticker">VMW:US</span>
    # - nearby politician profile links and trade metadata.
    ticker_pat = re.compile(r'<span[^>]*class="[^"]*issuer-ticker[^"]*"[^>]*>(?P<t>[^<]+)</span>', flags=re.I)
    pol_pat = re.compile(r'href="/politicians/[^"]+"[^>]*>(?P<n>[^<]{2,120})</a>', flags=re.I)
    date_pat = re.compile(r'>(?P<d>\d{1,2}\s+[A-Za-z]{3})</div>')
    tx_pat = re.compile(r'\b(Purchase|Sale|Sold|Buy|Bought)\b', flags=re.I)
    amt_pat = re.compile(r'\$[0-9][0-9,\.]*(?:[KMB])?(?:\s*-\s*\$[0-9][0-9,\.]*(?:[KMB])?)?', flags=re.I)

    for i, m in enumerate(ticker_pat.finditer(html)):
        raw_t = m.group("t").strip().upper()
        if raw_t in {"N/A", "NA", "-"}:
            continue
        ticker = raw_t.split(":")[0].strip()
        if not re.match(r"^[A-Z]{1,6}(?:\.[A-Z])?$", ticker):
            continue

        left = max(0, m.start() - 3500)
        right = min(len(html), m.end() + 3500)
        window = html[left:right]

        pol_matches = list(pol_pat.finditer(window))
        if not pol_matches:
            continue
        politician = pol_matches[-1].group("n").strip()

        date_matches = [x.group("d").strip() for x in date_pat.finditer(window)]
        trade_date_s = date_matches[0] if date_matches else None
        filing_date_s = date_matches[1] if len(date_matches) > 1 else None
        # Convert "27 Feb" to datetime using current year if no year in rendered UI.
        year = datetime.utcnow().year
        trade_date = None
        filing_date = None
        if trade_date_s:
            for y in (year, year - 1):
                try:
                    trade_date = datetime.strptime(f"{trade_date_s} {y}", "%d %b %Y")
                    break
                except Exception:
                    pass
        if filing_date_s:
            for y in (year, year - 1):
                try:
                    filing_date = datetime.strptime(f"{filing_date_s} {y}", "%d %b %Y")
                    break
                except Exception:
                    pass

        tx_m = tx_pat.search(window)
        amount_m = amt_pat.search(window)
        tx_type = tx_m.group(1).lower() if tx_m else None
        if tx_type == "bought":
            tx_type = "purchase"
        if tx_type == "buy":
            tx_type = "purchase"
        if tx_type == "sold":
            tx_type = "sale"
        amount_range = amount_m.group(0) if amount_m else None

        d = {
            "id": f"html_{i}_{ticker}_{(trade_date.date().isoformat() if trade_date else 'na')}",
            "ticker": ticker,
            "politician": politician,
            "transactionType": tx_type,
            "amount_range": amount_range,
            "tradeDate": trade_date.isoformat() if trade_date else None,
            "filingDate": filing_date.isoformat() if filing_date else None,
        }
        rec = _from_candidate(d, salt="html_cards")
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
