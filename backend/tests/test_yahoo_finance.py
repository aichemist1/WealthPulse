from app.connectors.yahoo_finance import parse_quote_summary_json


def test_parse_quote_summary_dividend_fields() -> None:
    json_text = """
    {
      "quoteSummary": {
        "result": [
          {
            "summaryDetail": {
              "dividendYield": {"raw": 0.0412},
              "trailingAnnualDividendYield": {"raw": 0.0399},
              "dividendRate": {"raw": 3.2},
              "trailingAnnualDividendRate": {"raw": 3.1},
              "exDividendDate": {"raw": 1735344000}
            },
            "defaultKeyStatistics": {
              "payoutRatio": {"raw": 0.52}
            }
          }
        ],
        "error": null
      }
    }
    """
    snap = parse_quote_summary_json(ticker="VNOM", json_text=json_text)
    assert snap.ticker == "VNOM"
    # Prefer trailingAnnualDividendYield when present
    assert snap.dividend_yield_ttm == 0.0399
    assert snap.payout_ratio == 0.52
    assert snap.forward_annual_dividend == 3.2
    assert snap.trailing_annual_dividend == 3.1
    assert snap.ex_dividend_date == "2024-12-28"

