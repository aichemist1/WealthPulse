from datetime import date

from app.snapshot.thirteenf_whales import HoldingValueRow, compute_13f_whales, previous_quarter_end


def test_previous_quarter_end():
    assert previous_quarter_end(date(2026, 3, 31)) == date(2025, 12, 31)
    assert previous_quarter_end(date(2026, 6, 30)) == date(2026, 3, 31)
    assert previous_quarter_end(date(2026, 9, 30)) == date(2026, 6, 30)
    assert previous_quarter_end(date(2026, 12, 31)) == date(2026, 9, 30)
    assert previous_quarter_end(date(2026, 2, 11)) is None


def test_compute_13f_whales_delta_and_manager_counts():
    current = [
        HoldingValueRow(investor_id="m1", cusip="AAA111111", value_usd=200),
        HoldingValueRow(investor_id="m2", cusip="AAA111111", value_usd=100),
        HoldingValueRow(investor_id="m2", cusip="BBB222222", value_usd=50),
    ]
    previous = [
        HoldingValueRow(investor_id="m1", cusip="AAA111111", value_usd=150),
        HoldingValueRow(investor_id="m2", cusip="AAA111111", value_usd=200),
    ]
    out = compute_13f_whales(current=current, previous=previous)
    by_c = {r.cusip: r for r in out}
    a = by_c["AAA111111"]
    assert a.total_value_usd == 300
    assert a.delta_value_usd == -50
    assert a.manager_count == 2
    assert a.manager_increase_count == 1  # m1 up
    assert a.manager_decrease_count == 1  # m2 down

