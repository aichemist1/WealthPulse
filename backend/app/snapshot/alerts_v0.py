from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import AdminAlert, SnapshotRecommendation, SnapshotRun
from app.snapshot.watchlists import compute_watchlist, parse_ticker_csv
from app.settings import settings


@dataclass(frozen=True)
class AlertsParams:
    limit: int = 50


def _upsert_alert(session: Session, alert: AdminAlert) -> bool:
    existing = session.exec(select(AdminAlert).where(AdminAlert.dedupe_key == alert.dedupe_key)).first()
    if existing is not None:
        return False
    session.add(alert)
    return True


def _latest_two_runs(session: Session, kind: str) -> tuple[Optional[SnapshotRun], Optional[SnapshotRun]]:
    runs = list(
        session.exec(
            select(SnapshotRun)
            .where(col(SnapshotRun.kind) == kind)
            .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
            .limit(2)
        ).all()
    )
    if not runs:
        return None, None
    if len(runs) == 1:
        return runs[0], None
    return runs[0], runs[1]


def new_action_tickers(
    *,
    cur_rows: list[SnapshotRecommendation],
    prev_rows: list[SnapshotRecommendation],
    action: str,
) -> set[str]:
    action_l = action.lower().strip()
    cur = {r.ticker for r in cur_rows if (r.action or "").lower() == action_l and r.ticker}
    prev = {r.ticker for r in prev_rows if (r.action or "").lower() == action_l and r.ticker}
    return cur - prev


def generate_alerts_v0(*, session: Session, params: AlertsParams = AlertsParams()) -> int:
    """
    Generate admin-only alerts:
    - Fresh BUY/AVOID appeared (from fresh_signals_v0 snapshots)
    - Trend flips for curated watchlists (ETFs + dividend stocks)
    """

    inserted = 0

    # Fresh signals: BUY/AVOID new appearances since previous run.
    cur, prev = _latest_two_runs(session, "fresh_signals_v0")
    if cur is not None:
        cur_rows = list(session.exec(select(SnapshotRecommendation).where(SnapshotRecommendation.run_id == cur.id)).all())
        prev_rows = (
            list(session.exec(select(SnapshotRecommendation).where(SnapshotRecommendation.run_id == prev.id)).all())
            if prev is not None
            else []
        )

        for action in ("buy", "avoid"):
            new = new_action_tickers(cur_rows=cur_rows, prev_rows=prev_rows, action=action)
            for t in sorted(new):
                dedupe = f"fresh:{action}:{t}:{cur.as_of.date().isoformat()}"
                severity = "high" if action == "buy" else "warn"
                if prev is None:
                    title = f"Fresh {action.upper()} (first run): {t}"
                    body = f"{t} is labeled {action.upper()} in Fresh Whale Signals (no prior run to diff)."
                    payload = {"run_id": cur.id, "as_of": cur.as_of.isoformat(), "first_run": True}
                else:
                    title = f"Fresh {action.upper()}: {t}"
                    body = f"{t} is newly labeled {action.upper()} in Fresh Whale Signals."
                    payload = {"run_id": cur.id, "as_of": cur.as_of.isoformat()}

                if _upsert_alert(
                    session,
                    AdminAlert(
                        dedupe_key=dedupe,
                        kind=f"fresh_{action}",
                        ticker=t,
                        severity=severity,
                        title=title,
                        body=body,
                        payload=payload,
                    ),
                ):
                    inserted += 1

    # Watchlist trend flips (based on latest two price bars available).
    # We treat flips as "recent" if bullish_recent/bearish_recent is computable (enough data).
    etfs = parse_ticker_csv(settings.watchlist_etfs)
    divs = parse_ticker_csv(settings.watchlist_dividend_stocks)
    tickers = list(dict.fromkeys(etfs + divs))
    if tickers:
        rows = compute_watchlist(session=session, tickers=tickers)
        # recompute "previous" by computing as-of the prior day of the last bar for each ticker
        for r in rows:
            if not r.as_of_date:
                continue
            try:
                y, m, d = (int(x) for x in r.as_of_date.split("-"))
                prev_day = datetime(y, m, d).date() - timedelta(days=1)
                prev_dt = datetime(prev_day.year, prev_day.month, prev_day.day, 23, 59, 59)
            except Exception:
                continue
            prev_rows = compute_watchlist(session=session, tickers=[r.ticker], as_of=prev_dt)
            if not prev_rows:
                continue
            p = prev_rows[0]
            if r.bullish_recent is None or r.bearish_recent is None:
                continue
            if p.bullish_recent is None or p.bearish_recent is None:
                continue

            # Bullish flip
            if p.bullish_recent is False and r.bullish_recent is True:
                dedupe = f"trend:bull:{r.ticker}:{r.as_of_date}"
                if _upsert_alert(
                    session,
                    AdminAlert(
                        dedupe_key=dedupe,
                        kind="trend_flip_bull",
                        ticker=r.ticker,
                        severity="info",
                        title=f"Trend flipped BULL: {r.ticker}",
                        body=f"{r.ticker} moved above SMA50 with positive 20D return.",
                        payload={"as_of_date": r.as_of_date, "close": r.close, "sma50": r.sma50, "return_20d": r.return_20d},
                    ),
                ):
                    inserted += 1

            # Bearish flip
            if p.bearish_recent is False and r.bearish_recent is True:
                dedupe = f"trend:bear:{r.ticker}:{r.as_of_date}"
                if _upsert_alert(
                    session,
                    AdminAlert(
                        dedupe_key=dedupe,
                        kind="trend_flip_bear",
                        ticker=r.ticker,
                        severity="warn",
                        title=f"Trend flipped BEAR: {r.ticker}",
                        body=f"{r.ticker} fell below SMA50 with negative 20D return.",
                        payload={"as_of_date": r.as_of_date, "close": r.close, "sma50": r.sma50, "return_20d": r.return_20d},
                    ),
                ):
                    inserted += 1

    if inserted:
        session.commit()
    return inserted
