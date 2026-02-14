from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


@dataclass(frozen=True)
class EdgarDailyIndexRow:
    cik: str
    company_name: str
    form_type: str
    date_filed: date
    filename: str  # Archives/edgar/data/.../*.txt

    @property
    def accession_number(self) -> Optional[str]:
        """
        Best-effort accession extraction from filename.
        Example filename:
          edgar/data/320193/0000320193-26-000012.txt
        """

        base = self.filename.rsplit("/", 1)[-1]
        if not base.endswith(".txt"):
            return None
        core = base[:-4]
        if core.count("-") == 2 and core.replace("-", "").isdigit():
            return core
        return None


def master_idx_url(day: date) -> str:
    """
    SEC EDGAR daily master index.
    Example:
      https://www.sec.gov/Archives/edgar/daily-index/2026/QTR1/master.20260210.idx
    """

    qtr = (day.month - 1) // 3 + 1
    return f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{qtr}/master.{day.strftime('%Y%m%d')}.idx"


def parse_master_idx(text: str) -> list[EdgarDailyIndexRow]:
    """
    Parse an EDGAR daily index file (pipe-separated).

    SEC publishes similar formats where:
    - header can be "...|Filename" or "...|File Name"
    - Date Filed can be YYYY-MM-DD or YYYYMMDD
    """

    rows: list[EdgarDailyIndexRow] = []
    in_data = False
    for line in text.splitlines():
        if not in_data:
            header = line.strip()
            if header.startswith("CIK|Company Name|Form Type|Date Filed|"):
                in_data = True
            continue
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 5:
            continue
        cik, company, form, date_filed_s, filename = (p.strip() for p in parts)
        if cik.isdigit():
            cik = cik.zfill(10)
        try:
            if "-" in date_filed_s:
                y, m, d = (int(x) for x in date_filed_s.split("-"))
                date_filed = date(y, m, d)
            else:
                date_filed = date(int(date_filed_s[0:4]), int(date_filed_s[4:6]), int(date_filed_s[6:8]))
        except Exception:
            continue
        rows.append(
            EdgarDailyIndexRow(
                cik=cik,
                company_name=company,
                form_type=form,
                date_filed=date_filed,
                filename=filename,
            )
        )
    return rows


def filter_rows(rows: Iterable[EdgarDailyIndexRow], *, form_types: set[str]) -> list[EdgarDailyIndexRow]:
    return [r for r in rows if r.form_type in form_types]
