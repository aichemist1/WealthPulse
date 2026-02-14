from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


_ACCEPTANCE_RE = re.compile(r"^ACCEPTANCE-DATETIME:\s*(\d{14})\s*$", re.MULTILINE)
_CONFORMED_PERIOD_RE = re.compile(r"^CONFORMED PERIOD OF REPORT:\s*(\d{8})\s*$", re.MULTILINE)
_FILED_AS_OF_RE = re.compile(r"^FILED AS OF DATE:\s*(\d{8})\s*$", re.MULTILINE)
_COMPANY_NAME_RE = re.compile(r"^COMPANY CONFORMED NAME:\s*(.+?)\s*$", re.MULTILINE)
_CIK_RE = re.compile(r"^CENTRAL INDEX KEY:\s*(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class SubmissionDocument:
    doc_type: str
    filename: Optional[str]
    text: str


@dataclass(frozen=True)
class ThirteenFFiling:
    filer_cik: Optional[str]
    filer_name: Optional[str]
    accession_number: Optional[str]
    report_period: Optional[date]
    filed_as_of: Optional[date]
    accepted_at: Optional[datetime]
    info_table_xml: Optional[str]


def extract_acceptance_datetime(filing_text: str) -> Optional[datetime]:
    m = _ACCEPTANCE_RE.search(filing_text)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _parse_yyyymmdd(s: str) -> Optional[date]:
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return None


def extract_report_period(filing_text: str) -> Optional[date]:
    m = _CONFORMED_PERIOD_RE.search(filing_text)
    if not m:
        return None
    return _parse_yyyymmdd(m.group(1))


def extract_filed_as_of(filing_text: str) -> Optional[date]:
    m = _FILED_AS_OF_RE.search(filing_text)
    if not m:
        return None
    return _parse_yyyymmdd(m.group(1))


def extract_filer_name(filing_text: str) -> Optional[str]:
    m = _COMPANY_NAME_RE.search(filing_text)
    if not m:
        return None
    return m.group(1).strip()


def extract_filer_cik(filing_text: str) -> Optional[str]:
    m = _CIK_RE.search(filing_text)
    if not m:
        return None
    return m.group(1).strip().zfill(10)


def parse_submission_documents(filing_text: str) -> list[SubmissionDocument]:
    """
    Parse SEC submission .txt into <DOCUMENT> blocks.
    """

    docs: list[SubmissionDocument] = []
    for m in re.finditer(r"(?is)<DOCUMENT>(.*?)</DOCUMENT>", filing_text):
        block = m.group(1)
        type_m = re.search(r"(?im)^<TYPE>(.+?)\s*$", block)
        doc_type = type_m.group(1).strip() if type_m else "UNKNOWN"
        fn_m = re.search(r"(?im)^<FILENAME>(.+?)\s*$", block)
        filename = fn_m.group(1).strip() if fn_m else None

        text_m = re.search(r"(?is)<TEXT>(.*)</TEXT>", block)
        text = text_m.group(1) if text_m else block
        docs.append(SubmissionDocument(doc_type=doc_type, filename=filename, text=text))
    return docs


def extract_information_table_xml(filing_text: str) -> Optional[str]:
    """
    Extract 13F information table XML from the submission.

    Prefer a document with TYPE containing 'INFORMATION TABLE' or 'INFOTABLE'.
    """

    docs = parse_submission_documents(filing_text)
    preferred = [d for d in docs if "INFORMATION TABLE" in d.doc_type.upper() or "INFOTABLE" in d.doc_type.upper()]
    candidates = preferred or docs

    def pick_xml(text: str) -> Optional[str]:
        xml_blocks = re.findall(r"(?is)<XML>(.*?)</XML>", text)
        if not xml_blocks:
            stripped = text.strip()
            if stripped.lower().startswith("<informationtable"):
                return stripped
            return None
        for b in xml_blocks:
            if re.search(r"(?i)<informationTable\b", b):
                return b.strip()
        return xml_blocks[0].strip() if xml_blocks else None

    for d in candidates:
        xml = pick_xml(d.text)
        if xml and re.search(r"(?i)<informationTable\b", xml):
            return xml

    return None


def parse_13f_filing_text(
    filing_text: str,
    *,
    accession_number: Optional[str] = None,
) -> ThirteenFFiling:
    return ThirteenFFiling(
        filer_cik=extract_filer_cik(filing_text),
        filer_name=extract_filer_name(filing_text),
        accession_number=accession_number,
        report_period=extract_report_period(filing_text),
        filed_as_of=extract_filed_as_of(filing_text),
        accepted_at=extract_acceptance_datetime(filing_text),
        info_table_xml=extract_information_table_xml(filing_text),
    )

