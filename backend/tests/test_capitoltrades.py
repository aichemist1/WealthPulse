from app.connectors.capitoltrades import parse_capitoltrades_html


def test_parse_capitoltrades_html_from_next_data() -> None:
    html = """
    <html><body>
      <script id="__NEXT_DATA__" type="application/json">
      {"props":{"pageProps":{"trades":[
        {"id":"tx1","representative":"S. Capito","ticker":"PLD","transactionType":"Purchase","amountRange":"$50,001 - $100,000","tradeDate":"2025-11-15","filingDate":"2025-12-10"}
      ]}}}
      </script>
    </body></html>
    """
    rows = parse_capitoltrades_html(html)
    assert len(rows) == 1
    r = rows[0]
    assert r.politician == "S. Capito"
    assert r.ticker == "PLD"
    assert (r.tx_type or "").startswith("purchase")
    assert r.filing_date is not None


def test_parse_capitoltrades_html_from_text_fallback() -> None:
    html = """
    <div>
      Democratic S. Capito traded PLD (Purchase) - $50,001 - $100,000 Filed 2025-12-10 Traded 2025-11-15
    </div>
    """
    rows = parse_capitoltrades_html(html)
    assert len(rows) == 1
    r = rows[0]
    assert r.ticker == "PLD"
    assert r.politician.endswith("Capito")
