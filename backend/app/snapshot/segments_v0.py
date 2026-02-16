from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import SnapshotRecommendation, SnapshotRun


@dataclass(frozen=True)
class SegmentPick:
    ticker: str
    score: int
    action: str
    confidence: float
    why: str
    source_kind: str  # recommendations_v0 | fresh_signals_v0


@dataclass(frozen=True)
class SegmentBucket:
    key: str
    name: str
    as_of: Optional[str]
    picks: list[SegmentPick]


@dataclass(frozen=True)
class SegmentCandidate:
    key: str
    priority: int
    strength: float
    pick: SegmentPick


def _latest_run(session: Session, kind: str) -> Optional[SnapshotRun]:
    return session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == kind)
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()


def _safe_get(d: Any, *path: str) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _fmt_millions(x: float) -> str:
    try:
        v = float(x)
    except Exception:
        return "n/a"
    sign = "-" if v < 0 else ""
    v = abs(v)
    if v >= 1_000_000_000:
        return f"{sign}{v/1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{sign}{v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"{sign}{v/1_000:.1f}K"
    return f"{sign}{v:.0f}"


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _choose_primary_segment(cands: list[SegmentCandidate]) -> Optional[SegmentCandidate]:
    """
    Primary segment selection by eligibility strength (not static bucket priority).

    Tie-breaker: lower priority value wins.
    Risk override: only force Risk when bearish evidence is materially stronger.
    """

    if not cands:
        return None
    by_strength = sorted(cands, key=lambda c: (c.strength, -c.priority), reverse=True)
    top = by_strength[0]

    # Avoid over-classifying as Risk on mixed setups.
    risk = next((c for c in by_strength if c.key == "risk"), None)
    if risk and top.key != "risk":
        if risk.strength >= (top.strength + 6.0):
            return risk

    return top


def compute_segments_v0(*, session: Session, picks_per_segment: int = 2) -> dict[str, Any]:
    """
    v0 segment buckets for the dashboard "Themes" row.

    Uses only signals we already compute:
    - Fresh whale signals: SC13 + Form4 + trend/volume (recent)
    - Top picks: 13F accumulation + corroborators (delayed context)

    Rule: one ticker appears in one segment (priority order).
    """

    fresh_run = _latest_run(session, "fresh_signals_v0")
    recs_run = _latest_run(session, "recommendations_v0")

    fresh_rows: list[SnapshotRecommendation] = []
    recs_rows: list[SnapshotRecommendation] = []
    if fresh_run is not None:
        fresh_rows = list(
            session.exec(
                select(SnapshotRecommendation)
                .where(SnapshotRecommendation.run_id == fresh_run.id)
                .order_by(col(SnapshotRecommendation.score).desc(), col(SnapshotRecommendation.confidence).desc())
            ).all()
        )
    if recs_run is not None:
        recs_rows = list(
            session.exec(
                select(SnapshotRecommendation)
                .where(SnapshotRecommendation.run_id == recs_run.id)
                .order_by(col(SnapshotRecommendation.score).desc(), col(SnapshotRecommendation.confidence).desc())
            ).all()
        )

    # Build one merged evidence view per ticker.
    fresh_by_ticker = {r.ticker: r for r in fresh_rows}
    recs_by_ticker = {r.ticker: r for r in recs_rows}
    all_tickers = sorted(set(fresh_by_ticker.keys()) | set(recs_by_ticker.keys()))

    SEGMENT_PRIORITY = {
        "insider": 1,
        "activist": 2,
        "institutional": 3,
        "momentum": 4,
        "risk": 5,
    }

    segment_picks: dict[str, list[SegmentCandidate]] = {k: [] for k in SEGMENT_PRIORITY.keys()}
    assignment: dict[str, str] = {}

    for ticker in all_tickers:
        fresh = fresh_by_ticker.get(ticker)
        recs = recs_by_ticker.get(ticker)

        fresh_reasons = (fresh.reasons if fresh else None) or {}
        rec_reasons = (recs.reasons if recs else None) or {}

        fresh_score = _to_int(fresh.score if fresh else 0, 0)
        fresh_conf = _to_float(fresh.confidence if fresh else 0.0, 0.0)
        rec_score = _to_int(recs.score if recs else 0, 0)
        rec_conf = _to_float(recs.confidence if recs else 0.0, 0.0)

        sc13_count = _to_int(_safe_get(fresh_reasons, "sc13", "count"), 0)
        sc13_latest = _safe_get(fresh_reasons, "sc13", "latest_filed_at")
        buy_value = _to_float(_safe_get(fresh_reasons, "insider", "buy_value"), 0.0)
        sell_value = _to_float(_safe_get(fresh_reasons, "insider", "sell_value"), 0.0)
        net_value = _to_float(_safe_get(fresh_reasons, "insider", "net_value"), buy_value - sell_value)
        cluster_buy = bool(_safe_get(fresh_reasons, "insider_quality", "cluster_buy") or False)
        trend_bull = bool(_safe_get(fresh_reasons, "trend_flags", "bullish_recent") or False)
        trend_bear = bool(_safe_get(fresh_reasons, "trend_flags", "bearish_recent") or False)
        ret20 = _safe_get(fresh_reasons, "trend", "return_20d")
        ret20_s = f"{float(ret20) * 100:.1f}%" if isinstance(ret20, (int, float)) else "n/a"

        delta = _to_float(_safe_get(rec_reasons, "delta_value_usd"), 0.0)
        inc = _to_int(_safe_get(rec_reasons, "breadth", "increase"), 0)
        total = max(1, _to_int(_safe_get(rec_reasons, "breadth", "total"), 0))
        breadth_ratio = inc / total
        trend_recent_top = bool(_safe_get(rec_reasons, "corroborators", "trend_bullish_recent") or False)
        trend_adj = _to_int(_safe_get(rec_reasons, "trend_adjustment"), 0)
        divergence_type = str(_safe_get(fresh_reasons, "divergence", "type") or "")

        cands: list[SegmentCandidate] = []

        if fresh and buy_value > 0:
            strength = float(fresh_score) + (4.0 if cluster_buy else 0.0) + min(6.0, (buy_value / 1_000_000.0))
            cands.append(
                SegmentCandidate(
                    key="insider",
                    priority=SEGMENT_PRIORITY["insider"],
                    strength=strength,
                    pick=SegmentPick(
                        ticker=ticker,
                        score=fresh_score,
                        action=fresh.action,
                        confidence=fresh_conf,
                        why=f"Insider net ${_fmt_millions(net_value)} · cluster {'yes' if cluster_buy else 'no'}",
                        source_kind="fresh_signals_v0",
                    ),
                )
            )

        if fresh and sc13_count > 0:
            strength = float(fresh_score) + min(8.0, 2.0 * float(sc13_count))
            cands.append(
                SegmentCandidate(
                    key="activist",
                    priority=SEGMENT_PRIORITY["activist"],
                    strength=strength,
                    pick=SegmentPick(
                        ticker=ticker,
                        score=fresh_score,
                        action=fresh.action,
                        confidence=fresh_conf,
                        why=f"SC13 x{sc13_count} · latest {str(sc13_latest)[:10] if sc13_latest else 'n/a'}",
                        source_kind="fresh_signals_v0",
                    ),
                )
            )

        if recs and delta > 0:
            strength = float(rec_score) + (10.0 * float(breadth_ratio)) + min(6.0, delta / 1_000_000_000.0)
            cands.append(
                SegmentCandidate(
                    key="institutional",
                    priority=SEGMENT_PRIORITY["institutional"],
                    strength=strength,
                    pick=SegmentPick(
                        ticker=ticker,
                        score=rec_score,
                        action=recs.action,
                        confidence=rec_conf,
                        why=f"13F Δ ${_fmt_millions(delta)} · mgrs {inc}/{total} · trend {trend_adj:+d}",
                        source_kind="recommendations_v0",
                    ),
                )
            )

        if (fresh and trend_bull and not trend_bear) or (recs and trend_recent_top):
            mom_score = max(fresh_score, rec_score)
            mom_conf = max(fresh_conf, rec_conf)
            mom_source = "fresh_signals_v0" if (fresh and trend_bull and not trend_bear) else "recommendations_v0"
            strength = float(mom_score) + (3.0 if trend_bull else 0.0)
            cands.append(
                SegmentCandidate(
                    key="momentum",
                    priority=SEGMENT_PRIORITY["momentum"],
                    strength=strength,
                    pick=SegmentPick(
                        ticker=ticker,
                        score=mom_score,
                        action=(fresh.action if fresh and mom_source == "fresh_signals_v0" else (recs.action if recs else "watch")),
                        confidence=mom_conf,
                        why=f"Trend bull · 20D {ret20_s}",
                        source_kind=mom_source,
                    ),
                )
            )

        risk_points = 0.0
        if fresh and fresh.action == "avoid":
            risk_points += 16.0
        if recs and recs.action == "avoid":
            risk_points += 10.0
        if trend_bear:
            risk_points += 10.0
        if sell_value > buy_value:
            risk_points += 8.0
        if divergence_type in {"bearish_divergence", "sc13_trend_conflict"}:
            risk_points += 8.0
        if risk_points > 0 and fresh:
            cands.append(
                SegmentCandidate(
                    key="risk",
                    priority=SEGMENT_PRIORITY["risk"],
                    strength=float(max(fresh_score, rec_score)) + risk_points,
                    pick=SegmentPick(
                        ticker=ticker,
                        score=max(fresh_score, rec_score),
                        action="avoid",
                        confidence=max(fresh_conf, rec_conf),
                        why=f"Bearish setup · insider sell ${_fmt_millions(sell_value)}",
                        source_kind="fresh_signals_v0",
                    ),
                )
            )

        primary = _choose_primary_segment(cands)
        if primary is None:
            continue
        assignment[ticker] = primary.key
        segment_picks[primary.key].append(primary)

    def _sort(xs: list[SegmentCandidate]) -> list[SegmentPick]:
        return [c.pick for c in sorted(xs, key=lambda c: (c.strength, c.pick.confidence), reverse=True)]

    insider_cands = _sort(segment_picks["insider"])
    activist_cands = _sort(segment_picks["activist"])
    inst_cands = _sort(segment_picks["institutional"])
    momentum_cands = _sort(segment_picks["momentum"])
    risk_cands = _sort(segment_picks["risk"])

    now = max(
        [x for x in [(fresh_run.as_of.isoformat() if fresh_run else None), (recs_run.as_of.isoformat() if recs_run else None)] if x],
        default=None,
    )
    def _bucket(key: str, name: str, as_of: Optional[str], picks: list[SegmentPick]) -> dict[str, Any]:
        return {
            "key": key,
            "name": name,
            "as_of": as_of,
            "picks": [p.__dict__ for p in picks[: max(1, picks_per_segment)]],
        }

    return {
        "as_of": now,
        "meta": {
            "selection": "eligibility_strength_primary_segment",
            "ticker_assignment_count": len(assignment),
        },
        "segments": [
            _bucket("insider", "Insider Activity", fresh_run.as_of.isoformat() if fresh_run else None, insider_cands),
            _bucket(
                "activist",
                "Activist / Large Owner",
                fresh_run.as_of.isoformat() if fresh_run else None,
                activist_cands,
            ),
            _bucket(
                "institutional",
                "Institutional Accumulation",
                recs_run.as_of.isoformat() if recs_run else None,
                inst_cands,
            ),
            _bucket(
                "momentum",
                "Momentum / Trend",
                max(
                    [
                        x
                        for x in [
                            (fresh_run.as_of.isoformat() if fresh_run else None),
                            (recs_run.as_of.isoformat() if recs_run else None),
                        ]
                        if x
                    ],
                    default=None,
                ),
                momentum_cands,
            ),
            _bucket("risk", "Risk / Avoid", fresh_run.as_of.isoformat() if fresh_run else None, risk_cands),
        ],
    }
