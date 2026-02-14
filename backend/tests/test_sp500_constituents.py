import pytest

from app.connectors.sp500_constituents import parse_sp500_constituents_csv


def test_parse_sp500_constituents_csv_symbol():
    csv = "Symbol,Security\nAAPL,Apple Inc.\nMSFT,Microsoft\n"
    rows = parse_sp500_constituents_csv(csv)
    assert [r.ticker for r in rows] == ["AAPL", "MSFT"]


def test_parse_sp500_constituents_csv_missing_col():
    with pytest.raises(ValueError):
        parse_sp500_constituents_csv("foo,bar\n1,2\n")

