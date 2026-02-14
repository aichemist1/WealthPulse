from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


_ACCEPTANCE_RE = re.compile(r"^ACCEPTANCE-DATETIME:\s*(\d{14})\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Sc13Parsed:
    issuer_cik: Optional[str]
    issuer_name: Optional[str]
    filer_cik: Optional[str]
    filer_name: Optional[str]
    accepted_at: Optional[datetime]


def extract_acceptance_datetime(filing_text: str) -> Optional[datetime]:
    m = _ACCEPTANCE_RE.search(filing_text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _extract_block(text: str, header: str) -> Optional[str]:
    """
    Extract a best-effort section block beginning at a header line like 'SUBJECT COMPANY:'.
    """

    idx = text.find(header)
    if idx == -1:
        return None
    # Take a bounded window; enough to include CIK + name lines.
    return text[idx : idx + 4000]


def _extract_cik(block: str) -> Optional[str]:
    m = re.search(r"^CENTRAL INDEX KEY:\s*(\d+)\s*$", block, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip().zfill(10)


def _extract_company_name(block: str) -> Optional[str]:
    m = re.search(r"^COMPANY CONFORMED NAME:\s*(.+?)\s*$", block, flags=re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip()


def parse_sc13_submission_text(filing_text: str) -> Sc13Parsed:
    """
    Parse a Schedule 13D/13G SEC submission .txt to identify:
    - issuer CIK/name (SUBJECT COMPANY)
    - filer CIK/name (FILED BY)

    This is intentionally light (header-only) for v0 corroboration gating.
    """

    accepted_at = extract_acceptance_datetime(filing_text)

    subject = _extract_block(filing_text, "SUBJECT COMPANY:")
    filed_by = _extract_block(filing_text, "FILED BY:")

    issuer_cik = _extract_cik(subject) if subject else None
    issuer_name = _extract_company_name(subject) if subject else None
    filer_cik = _extract_cik(filed_by) if filed_by else None
    filer_name = _extract_company_name(filed_by) if filed_by else None

    return Sc13Parsed(
        issuer_cik=issuer_cik,
        issuer_name=issuer_name,
        filer_cik=filer_cik,
        filer_name=filer_name,
        accepted_at=accepted_at,
    )

