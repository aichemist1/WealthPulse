from app.connectors.fmp_congress import parse_fmp_disclosures


def test_parse_fmp_disclosures_house_minimal() -> None:
    rows = parse_fmp_disclosures(
        [
            {
                "transaction_id": "abc123",
                "representative": "S. Capito",
                "ticker": "pld",
                "transactionDate": "2025-11-15",
                "disclosureDate": "2025-12-10",
                "amount_range": "$50k - $100k",
                "type": "Purchase",
            }
        ],
        chamber="house",
    )
    assert len(rows) == 1
    r = rows[0]
    assert r.source_id == "abc123"
    assert r.politician == "S. Capito"
    assert r.ticker == "PLD"
    assert r.chamber == "house"
    assert r.amount_range == "$50k - $100k"
    assert r.trade_date is not None
    assert r.filing_date is not None
