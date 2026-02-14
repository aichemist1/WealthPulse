from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlmodel import Session, select

from app.connectors.edgar_daily_index import filter_rows, master_idx_url, parse_master_idx
from app.connectors.edgar_form4_filing import parse_form4_filing_text
from app.connectors.form4 import parse_form4_xml
from app.connectors.sec_edgar import SecEdgarClient
from app.models import Event, Filing, InsiderTx, Investor, RawPayload, Stock


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class IngestResult:
    filings_seen: int
    filings_ingested: int
    transactions_inserted: int


def _upsert_stock(session: Session, ticker: str) -> Stock:
    stock = session.exec(select(Stock).where(Stock.ticker == ticker)).first()
    if stock is None:
        stock = Stock(ticker=ticker)
        session.add(stock)
        session.flush()
    return stock


def _upsert_investor(session: Session, name: str, cik: Optional[str]) -> Investor:
    if cik:
        investor = session.exec(select(Investor).where(Investor.cik == cik)).first()
        if investor is not None:
            return investor
    investor = session.exec(select(Investor).where(Investor.name == name)).first()
    if investor is None:
        investor = Investor(name=name, cik=cik)
        session.add(investor)
        session.flush()
    return investor


def _normalize_ticker(raw: Optional[str]) -> str:
    if not raw:
        return "UNKNOWN"
    t = raw.strip().upper()
    # Some filings include multiple tickers (e.g., "GEF, GEF-B"). Pick the first canonical token.
    if "," in t:
        t = t.split(",", 1)[0].strip()
    # Guard against accidental whitespace-separated multiple symbols.
    if " " in t:
        t = t.split(" ", 1)[0].strip()
    return t or "UNKNOWN"


def ingest_form4_day(
    *,
    session: Session,
    client: SecEdgarClient,
    day: date,
    universe_tickers: Optional[set[str]] = None,
    limit: int = 0,
) -> IngestResult:
    """
    Ingest all Form 4 filings filed on a given day via SEC master index.

    - Stores raw master.idx and filing .txt as RawPayload.
    - Normalizes to Filing/Event/InsiderTx.
    - Idempotent: uses uniqueness constraints + dedupe keys.
    """

    idx_url = master_idx_url(day)
    idx_bytes = client.get(idx_url, accept="text/plain")
    idx_text = idx_bytes.decode("latin-1", errors="replace")

    idx_payload = RawPayload(
        source="sec_edgar",
        source_id=f"master_idx:{day.isoformat()}",
        fetched_at=datetime.utcnow(),
        content_type="text/plain",
        sha256=_sha256(idx_bytes),
        payload=idx_bytes,
    )
    try:
        session.add(idx_payload)
        session.flush()
    except Exception:
        session.rollback()

    rows = filter_rows(parse_master_idx(idx_text), form_types={"4"})
    filings_seen = len(rows)

    filings_ingested = 0
    tx_inserted = 0

    for i, row in enumerate(rows):
        if limit and i >= limit:
            break

        accession = row.accession_number
        filing_url = f"https://www.sec.gov/Archives/{row.filename}"
        filing_bytes = client.get(filing_url, accept="text/plain")
        filing_text = filing_bytes.decode("latin-1", errors="replace")

        payload = RawPayload(
            source="sec_edgar",
            source_id=f"filing:{accession or row.filename}",
            fetched_at=datetime.utcnow(),
            content_type="text/plain",
            sha256=_sha256(filing_bytes),
            payload=filing_bytes,
        )
        try:
            session.add(payload)
            session.flush()
        except Exception:
            session.rollback()
            payload = session.exec(
                select(RawPayload).where(
                    RawPayload.source == "sec_edgar",
                    RawPayload.source_id == f"filing:{accession or row.filename}",
                )
            ).first()

        parsed = parse_form4_filing_text(filing_text, filename=row.filename)
        ownership_xml = parsed.ownership_xml
        if ownership_xml is None:
            continue

        txs = parse_form4_xml(ownership_xml)
        if not txs:
            continue

        ticker = _normalize_ticker(txs[0].issuer_trading_symbol)
        if universe_tickers is not None and ticker not in universe_tickers:
            continue

        filing = session.exec(
            select(Filing).where(Filing.source == "sec_edgar", Filing.accession_number == accession)
        ).first()
        if filing is None:
            filing = Filing(
                source="sec_edgar",
                form_type="4",
                accession_number=accession,
                filer_cik=txs[0].reporting_owner_cik,
                issuer_cik=txs[0].issuer_cik,
                filed_at=datetime.combine(row.date_filed, datetime.min.time()),
                accepted_at=parsed.accepted_at,
                raw_payload_id=payload.id if payload else None,
            )
            session.add(filing)
            session.flush()
            filings_ingested += 1

        stock = _upsert_stock(session, ticker)
        investor_name = txs[0].reporting_owner_name or "UNKNOWN"
        investor = _upsert_investor(session, investor_name, txs[0].reporting_owner_cik)

        for j, tx in enumerate(txs):
            dedupe_key = f"form4:{accession or row.filename}:{j}"
            if session.exec(select(Event).where(Event.dedupe_key == dedupe_key)).first() is not None:
                continue

            event_date = (
                datetime.combine(tx.transaction_date, datetime.min.time()) if tx.transaction_date else None
            )
            event = Event(
                event_type="insider_tx",
                dedupe_key=dedupe_key,
                stock_id=stock.id,
                investor_id=investor.id,
                filing_id=filing.id,
                event_date=event_date,
                filed_at=filing.filed_at,
                detected_at=datetime.utcnow(),
                data={
                    "transaction_code": tx.transaction_code,
                    "acquired_disposed": tx.acquired_disposed,
                    "shares": tx.shares,
                    "price_per_share": tx.price_per_share,
                    "shares_owned_following": tx.shares_owned_following,
                    "is_derivative": tx.is_derivative,
                },
            )
            session.add(event)
            session.flush()

            value = None
            if tx.shares is not None and tx.price_per_share is not None:
                value = float(tx.shares) * float(tx.price_per_share)

            insider_tx = InsiderTx(
                event_id=event.id,
                ticker=ticker,
                issuer_cik=tx.issuer_cik,
                insider_name=investor_name,
                insider_cik=tx.reporting_owner_cik,
                transaction_code=tx.transaction_code or "",
                acquired_disposed=tx.acquired_disposed,
                is_derivative=tx.is_derivative,
                shares=tx.shares,
                price=tx.price_per_share,
                transaction_value=value,
                shares_owned_following=tx.shares_owned_following,
                event_date=event_date,
                filed_at=filing.filed_at,
                detected_at=event.detected_at,
                source_accession=accession or row.filename,
                seq=j,
            )
            session.add(insider_tx)
            tx_inserted += 1

        session.commit()

    return IngestResult(
        filings_seen=filings_seen,
        filings_ingested=filings_ingested,
        transactions_inserted=tx_inserted,
    )
