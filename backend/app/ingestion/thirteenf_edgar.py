from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from sqlmodel import Session, select

from app.connectors.edgar_daily_index import filter_rows, master_idx_url, parse_master_idx
from app.connectors.edgar_13f_filing import parse_13f_filing_text
from app.connectors.form13f_info_table import parse_information_table_xml
from app.connectors.sec_edgar import SecEdgarClient
from app.models import Institution13FHolding, Institution13FReport, Investor, RawPayload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Ingest13FResult:
    filings_seen: int
    filings_ingested: int
    holdings_inserted: int


def _upsert_investor(session: Session, *, name: str, cik: Optional[str]) -> Investor:
    if cik:
        inv = session.exec(select(Investor).where(Investor.cik == cik)).first()
        if inv is not None:
            if name and inv.name != name:
                inv.name = name
                session.add(inv)
                session.flush()
            return inv
    inv = session.exec(select(Investor).where(Investor.name == name)).first()
    if inv is None:
        inv = Investor(name=name, cik=cik)
        session.add(inv)
        session.flush()
    return inv


def ingest_13f_day(
    *,
    session: Session,
    client: SecEdgarClient,
    day: date,
    limit: int = 0,
) -> Ingest13FResult:
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

    rows = filter_rows(parse_master_idx(idx_text), form_types={"13F-HR", "13F-HR/A"})
    filings_seen = len(rows)
    filings_ingested = 0
    holdings_inserted = 0

    for i, row in enumerate(rows):
        if limit and i >= limit:
            break

        accession = row.accession_number
        if accession is None:
            continue

        exists = session.exec(
            select(Institution13FReport).where(Institution13FReport.accession_number == accession)
        ).first()
        if exists is not None:
            continue

        filing_url = f"https://www.sec.gov/Archives/{row.filename}"
        filing_bytes = client.get(filing_url, accept="text/plain")
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

        parsed = parse_13f_filing_text(filing_text, accession_number=accession)
        if parsed.info_table_xml is None:
            continue

        holdings = parse_information_table_xml(parsed.info_table_xml)
        if not holdings:
            continue

        investor = _upsert_investor(
            session,
            name=parsed.filer_name or row.company_name or "UNKNOWN",
            cik=parsed.filer_cik or row.cik,
        )

        report_period_s = parsed.report_period.isoformat() if parsed.report_period else None
        filed_at = datetime.combine(day, datetime.min.time())

        report = Institution13FReport(
            investor_id=investor.id,
            accession_number=accession,
            report_period=report_period_s,
            filed_at=filed_at,
            accepted_at=parsed.accepted_at,
            raw_payload_id=payload.id if payload else None,
        )
        session.add(report)
        session.flush()
        filings_ingested += 1

        for j, h in enumerate(holdings):
            if not h.cusip:
                continue
            session.add(
                Institution13FHolding(
                    report_id=report.id,
                    cusip=h.cusip.strip(),
                    name_of_issuer=h.name_of_issuer,
                    title_of_class=h.title_of_class,
                    value_usd=h.value_usd,
                    shares=h.shares,
                    shares_type=h.shares_type,
                    put_call=h.put_call,
                    investment_discretion=h.investment_discretion,
                    voting_sole=h.voting_sole,
                    voting_shared=h.voting_shared,
                    voting_none=h.voting_none,
                    seq=j,
                )
            )
            holdings_inserted += 1

        session.commit()

    return Ingest13FResult(
        filings_seen=filings_seen,
        filings_ingested=filings_ingested,
        holdings_inserted=holdings_inserted,
    )
