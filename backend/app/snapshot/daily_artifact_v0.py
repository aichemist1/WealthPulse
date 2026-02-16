from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import SnapshotRecommendation, SnapshotRun
from app.snapshot.segments_v0 import compute_segments_v0


def _latest_run_leq(session: Session, kind: str, as_of: datetime) -> Optional[SnapshotRun]:
    return session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == kind)
        .where(col(SnapshotRun.as_of) <= as_of)
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()


def _rows_for_run(session: Session, run: Optional[SnapshotRun], *, top_n: int) -> list[dict[str, Any]]:
    if run is None:
        return []
    rows = list(
        session.exec(
            select(SnapshotRecommendation)
            .where(col(SnapshotRecommendation.run_id) == run.id)
            .order_by(col(SnapshotRecommendation.score).desc(), col(SnapshotRecommendation.confidence).desc())
            .limit(max(1, min(int(top_n), 500)))
        ).all()
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "ticker": r.ticker,
                "segment": r.segment,
                "action": r.action,
                "direction": r.direction,
                "score": int(r.score),
                "confidence": float(r.confidence),
                "reasons": r.reasons or {},
            }
        )
    return out


def _canonical_hash(payload: dict[str, Any]) -> str:
    b = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def build_daily_snapshot_payload_v0(
    *,
    session: Session,
    as_of: datetime,
    version: str = "v0.1",
    top_n_rows: int = 25,
    picks_per_segment: int = 3,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """
    Build a deterministic daily artifact payload + hash.
    """

    recs_run = _latest_run_leq(session, "recommendations_v0", as_of)
    fresh_run = _latest_run_leq(session, "fresh_signals_v0", as_of)
    seg = compute_segments_v0(session=session, picks_per_segment=picks_per_segment)

    source_runs = {
        "recommendations_v0": recs_run.id if recs_run else None,
        "fresh_signals_v0": fresh_run.id if fresh_run else None,
    }

    payload: dict[str, Any] = {
        "schema": "wealthpulse.daily_snapshot_artifact.v0",
        "version": version,
        "as_of": as_of.isoformat(),
        "source_runs": {
            "recommendations_v0": {
                "id": recs_run.id if recs_run else None,
                "as_of": recs_run.as_of.isoformat() if recs_run else None,
                "params": recs_run.params if recs_run else {},
            },
            "fresh_signals_v0": {
                "id": fresh_run.id if fresh_run else None,
                "as_of": fresh_run.as_of.isoformat() if fresh_run else None,
                "params": fresh_run.params if fresh_run else {},
            },
        },
        "recommendations_v0_top": _rows_for_run(session, recs_run, top_n=top_n_rows),
        "fresh_signals_v0_top": _rows_for_run(session, fresh_run, top_n=top_n_rows),
        "segments": seg,
    }

    digest = _canonical_hash(payload)
    return payload, digest, source_runs
