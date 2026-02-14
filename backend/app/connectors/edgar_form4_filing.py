from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


_ACCEPTANCE_RE = re.compile(r"^ACCEPTANCE-DATETIME:\s*(\d{14})\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Form4FilingDocument:
    accession_number: Optional[str]
    accepted_at: Optional[datetime]
    ownership_xml: Optional[str]


def extract_accession_from_filename(filename: str) -> Optional[str]:
    """
    edgar/data/320193/0000320193-26-000012.txt -> 0000320193-26-000012
    """

    base = filename.rsplit("/", 1)[-1]
    if base.endswith(".txt"):
        base = base[:-4]
    if base.count("-") == 2 and base.replace("-", "").isdigit():
        return base
    return None


def extract_acceptance_datetime(filing_text: str) -> Optional[datetime]:
    m = _ACCEPTANCE_RE.search(filing_text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def extract_ownership_xml(filing_text: str) -> Optional[str]:
    """
    Extract the Form 4 ownershipDocument XML embedded in the SEC .txt submission.
    Prefer the XML block that contains <ownershipDocument>.
    """

    # Many filings contain multiple <XML> blocks; try to choose the one with ownershipDocument.
    xml_blocks = re.findall(r"<XML>(.*?)</XML>", filing_text, flags=re.DOTALL | re.IGNORECASE)
    if not xml_blocks:
        return None

    for block in xml_blocks:
        if re.search(r"<ownershipDocument\b", block, flags=re.IGNORECASE):
            return block.strip()

    # Fall back: return first XML block.
    return xml_blocks[0].strip()


def parse_form4_filing_text(filing_text: str, *, filename: Optional[str] = None) -> Form4FilingDocument:
    accession = extract_accession_from_filename(filename) if filename else None
    accepted_at = extract_acceptance_datetime(filing_text)
    xml = extract_ownership_xml(filing_text)
    return Form4FilingDocument(accession_number=accession, accepted_at=accepted_at, ownership_xml=xml)

