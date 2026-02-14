from __future__ import annotations

from dataclasses import dataclass
from math import log1p
from typing import Optional


@dataclass(frozen=True)
class WhaleDeltaRow:
    ticker: str
    cusip: str
    delta_value_usd: int
    total_value_usd: int
    manager_count: int
    manager_increase_count: int
    manager_decrease_count: int
    security_type: Optional[str] = None
    security_type2: Optional[str] = None
    market_sector: Optional[str] = None


@dataclass
class RecommendationRow:
    ticker: str
    segment: str
    action: str  # buy|sell|watch
    direction: str  # bullish|bearish|neutral
    score: int  # 0..100
    confidence: float  # 0..1
    reasons: dict


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _is_equity(row: WhaleDeltaRow) -> bool:
    # Best-effort. OpenFIGI variants observed:
    # - marketSector: "Equity"
    # - securityType2: "Common Stock" / "Equity" / "ETF" / etc.
    ms = (row.market_sector or "").strip().lower()
    st = (row.security_type or "").strip().lower()
    st2 = (row.security_type2 or "").strip().lower()

    if ms and ms != "equity":
        return False

    # Exclude obvious fund/ETF wrappers.
    if "etf" in st or "etf" in st2:
        return False
    if "fund" in st or "fund" in st2:
        return False
    if "unit" in st2:
        return False

    # If we have type hints, accept common-stock-like equities.
    if st2:
        if st2 in {"equity", "common stock"}:
            return True
        # some results use "class a", etc; if it’s an equity market sector, allow.
        if ms == "equity":
            return True

    # Fallback: if no labels, allow and let later corroborators/gates handle.
    return ms == "equity" or (not ms and not st and not st2)


def _looks_like_etf_or_fund(ticker: str) -> bool:
    # Heuristic guardrail: many ETFs are 2-4 chars too, so this is intentionally light.
    # We'll rely mostly on OpenFIGI marketSector/securityType2 when available.
    return ticker.upper().endswith("IV")  # placeholder, keep minimal for now


def score_recommendations_from_13f(
    *,
    rows: list[WhaleDeltaRow],
    mapped_coverage_ratio: Optional[float],
    top_n: int = 20,
) -> list[RecommendationRow]:
    """
    Produce v0 recommendations from 13F whale deltas.

    IMPORTANT: 13F is delayed. This generates *idea-generation* picks with explicit reasons,
    not "whales bought today".
    """

    # Filter: require ticker and exclude non-equities when OpenFIGI labels are present.
    filtered: list[WhaleDeltaRow] = []
    for r in rows:
        if not r.ticker:
            continue
        # Top picks are bullish only (accumulation).
        if r.delta_value_usd <= 0:
            continue
        if not _is_equity(r):
            continue
        if _looks_like_etf_or_fund(r.ticker):
            continue
        filtered.append(r)

    if not filtered:
        return []

    # Rank by absolute delta magnitude for score component.
    sorted_by_abs = sorted(filtered, key=lambda r: abs(r.delta_value_usd), reverse=True)
    abs_rank = {r.ticker: i for i, r in enumerate(sorted_by_abs)}
    n = len(sorted_by_abs)
    max_rank = max(1, n - 1)
    max_abs_delta = max(abs(r.delta_value_usd) for r in filtered) if filtered else 1

    out: list[RecommendationRow] = []
    for r in filtered:
        direction = "bullish"

        # Score components (0..100)
        # - magnitude (rank-based): 0..55
        # - breadth: 0..25
        # - size: 0..10
        # - penalties: up to -20
        rank = abs_rank.get(r.ticker, max_rank)
        mag_component = 1.0 - (rank / max_rank)
        mag_score = 55.0 * mag_component

        breadth = (r.manager_increase_count / r.manager_count) if r.manager_count else 0.0
        breadth_score = 25.0 * breadth

        size_score = 10.0 * _clamp(log1p(max(r.total_value_usd, 0)) / log1p(100_000_000_000), 0.0, 1.0)

        penalty = 0.0
        # Coverage penalty: if mapping coverage is low, reduce confidence/score slightly.
        if mapped_coverage_ratio is not None:
            coverage_pen = 10.0 * _clamp(0.20 - mapped_coverage_ratio, 0.0, 0.20) / 0.20
            penalty += coverage_pen
        else:
            coverage_pen = 0.0

        # Sample-size penalty for tiny manager counts.
        if r.manager_count < 3:
            sample_pen = 6.0
            penalty += sample_pen
        else:
            sample_pen = 0.0

        base = mag_score + breadth_score + size_score - penalty

        score = int(round(_clamp(base, 0.0, 100.0)))

        # Confidence is deliberately capped because 13F is delayed.
        conf = 0.20
        conf += 0.15 * _clamp(log1p(r.manager_count) / log1p(25), 0.0, 1.0)
        conf += 0.20 * _clamp(abs(r.delta_value_usd) / max_abs_delta, 0.0, 1.0)
        if mapped_coverage_ratio is not None:
            conf -= 0.15 * _clamp(0.10 - mapped_coverage_ratio, 0.0, 0.10) / 0.10
        conf = float(_clamp(conf, 0.05, 0.65))

        # Action: v0 uses 13F-only signal, so default to Watch.
        action = "watch"

        reasons = {
            "signal": "13F quarter-over-quarter delta (delayed)",
            "delta_value_usd": r.delta_value_usd,
            "total_value_usd": r.total_value_usd,
            "breadth": {"increase": r.manager_increase_count, "decrease": r.manager_decrease_count, "total": r.manager_count},
            "rank_abs_delta": abs_rank.get(r.ticker, 0) + 1,
            "universe_size": n,
            "score_breakdown": {
                "magnitude": {"score": mag_score, "component": mag_component, "rank": rank + 1, "max_rank": max_rank + 1},
                "breadth": {"score": breadth_score, "component": breadth, "increase": r.manager_increase_count, "total": r.manager_count},
                "size": {"score": size_score, "total_value_usd": r.total_value_usd},
                "penalty": {
                    "total": penalty,
                    "coverage": coverage_pen,
                    "sample_size": sample_pen,
                    "mapped_coverage_ratio": mapped_coverage_ratio,
                },
            },
        }

        out.append(
            RecommendationRow(
                ticker=r.ticker,
                segment="Institutional Accumulation (13F)",
                action=action,
                direction=direction,
                score=score,
                confidence=conf,
                reasons=reasons,
            )
        )

    # Top picks: sort by score desc, then confidence.
    return sorted(out, key=lambda x: (x.score, x.confidence), reverse=True)[:top_n]
