from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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

    # Candidate pools (derived from reasons so we don't have to query extra tables).
    insider_cands: list[SegmentPick] = []
    activist_cands: list[SegmentPick] = []
    momentum_cands: list[SegmentPick] = []
    risk_cands: list[SegmentPick] = []
    inst_cands: list[SegmentPick] = []

    for r in fresh_rows:
        reasons = r.reasons or {}
        sc13_count = int(_safe_get(reasons, "sc13", "count") or 0)
        sc13_latest = _safe_get(reasons, "sc13", "latest_filed_at")
        buy_value = float(_safe_get(reasons, "insider", "buy_value") or 0.0)
        sell_value = float(_safe_get(reasons, "insider", "sell_value") or 0.0)
        net_value = float(_safe_get(reasons, "insider", "net_value") or (buy_value - sell_value))
        trend_bull = bool(_safe_get(reasons, "trend_flags", "bullish_recent") or False)
        trend_bear = bool(_safe_get(reasons, "trend_flags", "bearish_recent") or False)
        ret20 = _safe_get(reasons, "trend", "return_20d")
        ret20_s = f"{float(ret20) * 100:.1f}%" if isinstance(ret20, (int, float)) else "n/a"

        if buy_value > 0:
            insider_cands.append(
                SegmentPick(
                    ticker=r.ticker,
                    score=int(r.score),
                    action=r.action,
                    confidence=float(r.confidence),
                    why=f"Insider net ${_fmt_millions(net_value)} · Trend {'bull' if trend_bull else 'n/a'}",
                    source_kind="fresh_signals_v0",
                )
            )
        if sc13_count > 0:
            activist_cands.append(
                SegmentPick(
                    ticker=r.ticker,
                    score=int(r.score),
                    action=r.action,
                    confidence=float(r.confidence),
                    why=f"SC13 x{sc13_count} · latest {str(sc13_latest)[:10] if sc13_latest else 'n/a'}",
                    source_kind="fresh_signals_v0",
                )
            )
        if trend_bull:
            momentum_cands.append(
                SegmentPick(
                    ticker=r.ticker,
                    score=int(r.score),
                    action=r.action,
                    confidence=float(r.confidence),
                    why=f"Trend bull · 20D {ret20_s}",
                    source_kind="fresh_signals_v0",
                )
            )
        if r.action == "avoid" or trend_bear or sell_value > buy_value:
            risk_cands.append(
                SegmentPick(
                    ticker=r.ticker,
                    score=int(r.score),
                    action=r.action,
                    confidence=float(r.confidence),
                    why=f"Bearish setup · insider sell ${_fmt_millions(sell_value)}",
                    source_kind="fresh_signals_v0",
                )
            )

    for r in recs_rows:
        reasons = r.reasons or {}
        delta = _safe_get(reasons, "delta_value_usd")
        inc = _safe_get(reasons, "breadth", "increase")
        total = _safe_get(reasons, "breadth", "total")
        trend_recent = bool(_safe_get(reasons, "corroborators", "trend_bullish_recent") or False)
        trend_adj = int(_safe_get(reasons, "trend_adjustment") or 0)
        inst_cands.append(
            SegmentPick(
                ticker=r.ticker,
                score=int(r.score),
                action=r.action,
                confidence=float(r.confidence),
                why=f"13F Δ ${_fmt_millions(float(delta or 0))} · mgrs {int(inc or 0)}/{int(total or 0)} · trend {trend_adj:+d}",
                source_kind="recommendations_v0",
            )
        )
        if trend_recent:
            momentum_cands.append(
                SegmentPick(
                    ticker=r.ticker,
                    score=int(r.score),
                    action=r.action,
                    confidence=float(r.confidence),
                    why=f"Trend bull · from Top Picks",
                    source_kind="recommendations_v0",
                )
            )

    # Stable ordering: score desc then confidence.
    def _sort(xs: list[SegmentPick]) -> list[SegmentPick]:
        return sorted(xs, key=lambda p: (p.score, p.confidence), reverse=True)

    insider_cands = _sort(insider_cands)
    activist_cands = _sort(activist_cands)
    inst_cands = _sort(inst_cands)
    momentum_cands = _sort(momentum_cands)
    risk_cands = _sort(risk_cands)

    # Apply one-ticker-one-segment in priority order.
    used: set[str] = set()

    def _take(cands: list[SegmentPick]) -> list[SegmentPick]:
        out: list[SegmentPick] = []
        for p in cands:
            if p.ticker in used:
                continue
            used.add(p.ticker)
            out.append(p)
            if len(out) >= picks_per_segment:
                break
        return out

    now = datetime.utcnow().isoformat()
    def _bucket(key: str, name: str, as_of: Optional[str], picks: list[SegmentPick]) -> dict[str, Any]:
        return {
            "key": key,
            "name": name,
            "as_of": as_of,
            "picks": [p.__dict__ for p in picks],
        }

    return {
        "as_of": now,
        "segments": [
            _bucket("insider", "Insider Activity", fresh_run.as_of.isoformat() if fresh_run else None, _take(insider_cands)),
            _bucket(
                "activist",
                "Activist / Large Owner",
                fresh_run.as_of.isoformat() if fresh_run else None,
                _take(activist_cands),
            ),
            _bucket(
                "institutional",
                "Institutional Accumulation",
                recs_run.as_of.isoformat() if recs_run else None,
                _take(inst_cands),
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
                _take(momentum_cands),
            ),
            _bucket("risk", "Risk / Avoid", fresh_run.as_of.isoformat() if fresh_run else None, _take(risk_cands)),
        ],
    }
