from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlmodel import Session, select

from app.connectors.edgar_daily_index import master_idx_url, parse_master_idx
from app.connectors.edgar_sc13_filing import parse_sc13_submission_text
from app.connectors.sec_company_tickers import build_cik_to_ticker, fetch_company_tickers
from app.connectors.sec_edgar import SecEdgarClient
from app.models import LargeOwnerFiling, RawPayload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class IngestSc13Result:
    filings_seen: int
    filings_ingested: int


def _is_sc13(form_type: str) -> bool:
    ft = form_type.upper().strip()
    return ft.startswith("SC 13D") or ft.startswith("SC 13G") or ft.startswith("SCHEDULE 13D") or ft.startswith("SCHEDULE 13G")


def ingest_sc13_day(
    *,
    session: Session,
    client: SecEdgarClient,
    day: date,
    universe_tickers: Optional[set[str]] = None,
    limit: int = 0,
) -> IngestSc13Result:
    idx_bytes = client.get(master_idx_url(day), accept="text/plain")
    idx_text = idx_bytes.decode("latin-1", errors="replace")
    rows = [r for r in parse_master_idx(idx_text) if _is_sc13(r.form_type)]
    filings_seen = len(rows)

    # Download ticker mapping once per run.
    cik_to_ticker = build_cik_to_ticker(fetch_company_tickers(client))

    filings_ingested = 0
    for i, row in enumerate(rows):
        if limit and i >= limit:
            break
        accession = row.accession_number
        if not accession:
            continue

        if session.exec(select(LargeOwnerFiling).where(LargeOwnerFiling.source_accession == accession)).first() is not None:
            continue

        filing_bytes = client.get(f"https://www.sec.gov/Archives/{row.filename}", accept="text/plain")
        filing_text = filing_bytes.decode("latin-1", errors="replace")

        payload = RawPayload(
            source="sec_edgar",
            source_id=f"filing:{accession}",
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
                select(RawPayload).where(RawPayload.source == "sec_edgar", RawPayload.source_id == f"filing:{accession}")
            ).first()

        parsed = parse_sc13_submission_text(filing_text)
        issuer_cik = parsed.issuer_cik
        ticker = cik_to_ticker.get(issuer_cik or "")
        if not ticker:
            continue
        if universe_tickers is not None and ticker not in universe_tickers:
            continue

        session.add(
            LargeOwnerFiling(
                source_accession=accession,
                form_type=row.form_type,
                ticker=ticker,
                issuer_cik=issuer_cik,
                filer_cik=parsed.filer_cik or row.cik,
                filer_name=parsed.filer_name or row.company_name,
                filed_at=datetime.combine(row.date_filed, datetime.min.time()),
                accepted_at=parsed.accepted_at,
                detected_at=datetime.utcnow(),
                raw_payload_id=payload.id if payload else None,
            )
        )
        session.commit()
        filings_ingested += 1

    return IngestSc13Result(filings_seen=filings_seen, filings_ingested=filings_ingested)

