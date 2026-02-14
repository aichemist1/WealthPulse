import pytest

from app.security_map import parse_security_map_csv


def test_parse_security_map_csv_minimal():
    csv = "cusip,ticker\n037833100,AAPL\n"
    rows = parse_security_map_csv(csv)
    assert len(rows) == 1
    assert rows[0].cusip == "037833100"
    assert rows[0].ticker == "AAPL"


def test_parse_security_map_csv_missing_header():
    with pytest.raises(ValueError):
        parse_security_map_csv("foo,bar\n1,2\n")

