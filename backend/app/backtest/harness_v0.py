from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from statistics import mean
from typing import Iterable, Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import PriceBar, SnapshotRecommendation, SnapshotRun


@dataclass(frozen=True)
class BacktestMetric:
    source_kind: str
    action: str
    horizon_days: int
    attempted: int
    evaluated: int
    coverage: float
    avg_ticker_return: Optional[float]
    avg_baseline_return: Optional[float]
    avg_excess_return: Optional[float]
    hit_rate_vs_baseline: Optional[float]


def _to_date(dt: datetime) -> date:
    return dt.date()


def _parse_bar_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(s))
    except Exception:
        return None


def _price_index(session: Session, tickers: Iterable[str]) -> dict[str, list[tuple[date, float]]]:
    ts = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    if not ts:
        return {}
    rows = list(
        session.exec(
            select(PriceBar.ticker, PriceBar.date, PriceBar.close)
            .where(col(PriceBar.ticker).in_(ts))
            .order_by(col(PriceBar.ticker), col(PriceBar.date))
        ).all()
    )
    out: dict[str, list[tuple[date, float]]] = {}
    for t, ds, c in rows:
        d = _parse_bar_date(str(ds))
        if d is None:
            continue
        out.setdefault(str(t).upper(), []).append((d, float(c)))
    return out


def _forward_return(bars: list[tuple[date, float]], as_of_date: date, horizon_days: int) -> Optional[float]:
    if not bars or horizon_days <= 0:
        return None
    entry_idx = None
    for i, (d, _c) in enumerate(bars):
        if d <= as_of_date:
            entry_idx = i
        else:
            break
    if entry_idx is None:
        return None
    exit_idx = entry_idx + int(horizon_days)
    if exit_idx >= len(bars):
        return None
    entry = float(bars[entry_idx][1])
    exit_ = float(bars[exit_idx][1])
    if entry <= 0:
        return None
    return (exit_ - entry) / entry


def run_backtest_v0(
    *,
    session: Session,
    start_as_of: datetime,
    end_as_of: datetime,
    source_kinds: list[str],
    baseline_ticker: str = "SPY",
    horizons: list[int] = [5, 20],
    top_n_per_action: int = 5,
) -> dict:
    kinds = [k.strip() for k in source_kinds if k.strip()]
    if not kinds:
        kinds = ["recommendations_v0", "fresh_signals_v0"]

    runs = list(
        session.exec(
            select(SnapshotRun)
            .where(col(SnapshotRun.kind).in_(kinds))
            .where(col(SnapshotRun.as_of) >= start_as_of)
            .where(col(SnapshotRun.as_of) <= end_as_of)
            .order_by(col(SnapshotRun.as_of), col(SnapshotRun.created_at))
        ).all()
    )

    recs_by_run: dict[str, list[SnapshotRecommendation]] = {}
    all_tickers: set[str] = {baseline_ticker.strip().upper()}
    for run in runs:
        rows = list(
            session.exec(
                select(SnapshotRecommendation)
                .where(col(SnapshotRecommendation.run_id) == run.id)
                .order_by(col(SnapshotRecommendation.score).desc(), col(SnapshotRecommendation.confidence).desc())
                .limit(200)
            ).all()
        )
        recs_by_run[run.id] = rows
        for r in rows:
            all_tickers.add(str(r.ticker).upper())

    prices = _price_index(session, all_tickers)
    baseline = prices.get(baseline_ticker.strip().upper(), [])

    attempted: dict[tuple[str, str, int], int] = {}
    ticker_returns: dict[tuple[str, str, int], list[float]] = {}
    base_returns: dict[tuple[str, str, int], list[float]] = {}
    excess_values: dict[tuple[str, str, int], list[float]] = {}
    hits: dict[tuple[str, str, int], int] = {}

    actions = ["buy", "avoid"]
    for run in runs:
        run_rows = recs_by_run.get(run.id, [])
        by_action = {
            a: [r for r in run_rows if str(r.action).lower() == a][: max(1, int(top_n_per_action))]
            for a in actions
        }
        as_of_date = _to_date(run.as_of)
        for h in horizons:
            bret = _forward_return(baseline, as_of_date, int(h))
            for action in actions:
                rows = by_action[action]
                key = (run.kind, action, int(h))
                attempted[key] = attempted.get(key, 0) + len(rows)
                if bret is None:
                    continue
                for r in rows:
                    bars = prices.get(str(r.ticker).upper(), [])
                    tret = _forward_return(bars, as_of_date, int(h))
                    if tret is None:
                        continue
                    ticker_returns.setdefault(key, []).append(tret)
                    base_returns.setdefault(key, []).append(bret)
                    if action == "buy":
                        ex = tret - bret
                        hit = 1 if tret > bret else 0
                    else:
                        ex = bret - tret
                        hit = 1 if tret < bret else 0
                    excess_values.setdefault(key, []).append(ex)
                    hits[key] = hits.get(key, 0) + hit

    metrics: list[dict] = []
    for kind in kinds:
        for action in actions:
            for h in horizons:
                key = (kind, action, int(h))
                tr = ticker_returns.get(key, [])
                br = base_returns.get(key, [])
                ex = excess_values.get(key, [])
                eval_n = len(tr)
                att = int(attempted.get(key, 0))
                metrics.append(
                    BacktestMetric(
                        source_kind=kind,
                        action=action,
                        horizon_days=int(h),
                        attempted=att,
                        evaluated=eval_n,
                        coverage=(float(eval_n) / float(att)) if att > 0 else 0.0,
                        avg_ticker_return=(mean(tr) if tr else None),
                        avg_baseline_return=(mean(br) if br else None),
                        avg_excess_return=(mean(ex) if ex else None),
                        hit_rate_vs_baseline=((float(hits.get(key, 0)) / float(eval_n)) if eval_n > 0 else None),
                    ).__dict__
                )

    return {
        "window": {"start_as_of": start_as_of.isoformat(), "end_as_of": end_as_of.isoformat()},
        "source_kinds": kinds,
        "baseline_ticker": baseline_ticker.strip().upper(),
        "horizons": [int(h) for h in horizons],
        "runs_considered": len(runs),
        "metrics": metrics,
    }
