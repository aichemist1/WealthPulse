from datetime import datetime

from app.models import InsiderTx
from app.snapshot.insider_whales import compute_insider_whales


def test_compute_insider_whales_aggregates_and_filters():
    rows = [
        InsiderTx(
            event_id="e1",
            ticker="AAA",
            insider_name="X",
            transaction_code="P",
            is_derivative=False,
            transaction_value=300_000,
            event_date=datetime(2026, 2, 10),
            source_accession="a",
            seq=0,
        ),
        InsiderTx(
            event_id="e2",
            ticker="AAA",
            insider_name="Y",
            transaction_code="P",
            is_derivative=False,
            transaction_value=400_000,
            event_date=datetime(2026, 2, 11),
            source_accession="b",
            seq=0,
        ),
        InsiderTx(
            event_id="e3",
            ticker="BBB",
            insider_name="Z",
            transaction_code="S",
            is_derivative=False,
            transaction_value=9_999_999,
            event_date=datetime(2026, 2, 11),
            source_accession="c",
            seq=0,
        ),
        InsiderTx(
            event_id="e4",
            ticker="CCC",
            insider_name="W",
            transaction_code="P",
            is_derivative=True,
            transaction_value=9_999_999,
            event_date=datetime(2026, 2, 11),
            source_accession="d",
            seq=0,
        ),
    ]

    out = compute_insider_whales(rows=rows, min_value=250_000)
    assert [r.ticker for r in out] == ["AAA"]
    assert out[0].total_purchase_value == 700_000
    assert out[0].purchase_tx_count == 2
    assert out[0].latest_event_date == datetime(2026, 2, 11)

