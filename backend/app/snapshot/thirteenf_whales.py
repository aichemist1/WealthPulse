from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


@dataclass(frozen=True)
class HoldingValueRow:
    investor_id: str
    cusip: str
    value_usd: int


@dataclass(frozen=True)
class ThirteenFWhaleRow:
    cusip: str
    total_value_usd: int
    delta_value_usd: int
    manager_count: int
    manager_increase_count: int
    manager_decrease_count: int


def previous_quarter_end(report_period: date) -> Optional[date]:
    """
    13F report periods are typically quarter ends: 03/31, 06/30, 09/30, 12/31.
    """

    if (report_period.month, report_period.day) == (3, 31):
        return date(report_period.year - 1, 12, 31)
    if (report_period.month, report_period.day) == (6, 30):
        return date(report_period.year, 3, 31)
    if (report_period.month, report_period.day) == (9, 30):
        return date(report_period.year, 6, 30)
    if (report_period.month, report_period.day) == (12, 31):
        return date(report_period.year, 9, 30)
    return None


def compute_13f_whales(
    *,
    current: Iterable[HoldingValueRow],
    previous: Iterable[HoldingValueRow],
    universe_cusips: Optional[set[str]] = None,
) -> list[ThirteenFWhaleRow]:
    """
    Compute quarter-over-quarter aggregate value + manager increase/decrease counts by CUSIP.
    """

    cur_by_mgr: dict[tuple[str, str], int] = {}
    prev_by_mgr: dict[tuple[str, str], int] = {}
    cur_totals: dict[str, int] = {}
    prev_totals: dict[str, int] = {}

    def include(cusip: str) -> bool:
        return universe_cusips is None or cusip in universe_cusips

    for r in current:
        if not include(r.cusip):
            continue
        cur_by_mgr[(r.investor_id, r.cusip)] = cur_by_mgr.get((r.investor_id, r.cusip), 0) + int(r.value_usd)
        cur_totals[r.cusip] = cur_totals.get(r.cusip, 0) + int(r.value_usd)

    for r in previous:
        if not include(r.cusip):
            continue
        prev_by_mgr[(r.investor_id, r.cusip)] = prev_by_mgr.get((r.investor_id, r.cusip), 0) + int(r.value_usd)
        prev_totals[r.cusip] = prev_totals.get(r.cusip, 0) + int(r.value_usd)

    cusips = set(cur_totals.keys()) | set(prev_totals.keys())

    out: list[ThirteenFWhaleRow] = []
    for cusip in cusips:
        total_cur = cur_totals.get(cusip, 0)
        total_prev = prev_totals.get(cusip, 0)
        delta = total_cur - total_prev

        mgrs = set(m for (m, c) in cur_by_mgr.keys() if c == cusip) | set(m for (m, c) in prev_by_mgr.keys() if c == cusip)
        inc = 0
        dec = 0
        for m in mgrs:
            v_cur = cur_by_mgr.get((m, cusip), 0)
            v_prev = prev_by_mgr.get((m, cusip), 0)
            if v_cur > v_prev:
                inc += 1
            elif v_cur < v_prev:
                dec += 1

        out.append(
            ThirteenFWhaleRow(
                cusip=cusip,
                total_value_usd=total_cur,
                delta_value_usd=delta,
                manager_count=len(mgrs),
                manager_increase_count=inc,
                manager_decrease_count=dec,
            )
        )

    return sorted(out, key=lambda r: r.delta_value_usd, reverse=True)

