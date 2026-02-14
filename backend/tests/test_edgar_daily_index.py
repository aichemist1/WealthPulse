from datetime import date

from app.connectors.edgar_daily_index import master_idx_url, parse_master_idx


def test_master_idx_url_quarter():
    assert (
        master_idx_url(date(2026, 2, 10))
        == "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR1/master.20260210.idx"
    )
    assert (
        master_idx_url(date(2026, 6, 1))
        == "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR2/master.20260601.idx"
    )


def test_parse_master_idx_minimal():
    text = """Description:           Master Index of EDGAR Dissemination Feed
Last Data Received:     February 10, 2026

CIK|Company Name|Form Type|Date Filed|File Name
0000320193|APPLE INC|4|2026-02-10|edgar/data/320193/0000320193-26-000012.txt
0000000000|SOME CO|10-K|20260210|edgar/data/0/0000000000-26-000001.txt
"""
    rows = parse_master_idx(text)
    assert len(rows) == 2
    assert rows[0].cik == "0000320193"
    assert rows[0].form_type == "4"
    assert rows[0].accession_number == "0000320193-26-000012"
