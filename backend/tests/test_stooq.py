from app.connectors.stooq import parse_daily_csv, stooq_symbol_for_ticker


def test_stooq_symbol_for_ticker():
    assert stooq_symbol_for_ticker("AAPL") == "aapl.us"
    assert stooq_symbol_for_ticker("brk.b") == "brk.b"


def test_parse_daily_csv_minimal():
    csv = "Date,Open,High,Low,Close,Volume\n2026-02-10,1,1,1,10,100\n2026-02-11,1,1,1,12,200\n"
    bars = parse_daily_csv(csv)
    assert len(bars) == 2
    assert bars[-1].close == 12.0

