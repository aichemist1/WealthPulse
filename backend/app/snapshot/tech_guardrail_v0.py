from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TechGuardrailResult:
    score_before: int
    score_after: int
    ft: float
    adj: int
    notes: list[str]


def _clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def apply_tech_guardrail_v0(*, score: int, tech: Optional[dict]) -> TechGuardrailResult:
    """
    Apply a lightweight "entry quality" guardrail to the score.

    This is deliberately NOT a full technical system; it is a simple penalty/boost layer:
    - Penalize chasing (extended above SMA50, near 60D high)
    - Lightly boost when near support (near SMA50 while bullish)

    Returns the updated score plus an auditable breakdown for the UI.
    """

    score_i = int(score)
    if not tech:
        return TechGuardrailResult(score_before=score_i, score_after=score_i, ft=1.0, adj=0, notes=["no technical data"])

    bullish = bool(tech.get("bullish"))
    extended_up = bool(tech.get("extended_up"))
    near_support = bool(tech.get("near_support"))
    near_res = bool(tech.get("near_resistance_60d"))
    below_sma200 = bool(tech.get("below_sma200"))

    ft = 1.0
    adj = 0
    notes: list[str] = []

    if bullish and near_support:
        ft *= 1.05
        adj += 2
        notes.append("near SMA50 support")

    if bullish and (extended_up or near_res):
        ft *= 0.90
        if extended_up:
            notes.append("extended above SMA50")
        if near_res:
            notes.append("near 60D high")

    # Slow trend penalty: below SMA200 is a long-term risk flag.
    # Keep it small; this is guardrail, not a signal.
    if below_sma200 and not bullish:
        adj -= 3
        notes.append("below SMA200")

    score_after = int(round(score_i * ft + adj))
    score_after = _clamp_int(score_after, 0, 100)
    return TechGuardrailResult(
        score_before=score_i,
        score_after=score_after,
        ft=float(ft),
        adj=int(adj),
        notes=notes or ["neutral"],
    )

