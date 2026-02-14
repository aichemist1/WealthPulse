from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log1p
from typing import Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import InsiderTx, LargeOwnerFiling, PriceBar, Security, Snapshot13FWhale, SnapshotRun
from app.snapshot.trend import compute_trend_from_closes


@dataclass(frozen=True)
class FreshSignalParams:
    as_of: datetime
    fresh_days: int = 7
    insider_min_value: float = 100_000.0
    top_n: int = 20
    buy_score_threshold: int = 75
    avoid_score_threshold: int = 35


@dataclass
class FreshSignalRow:
    ticker: str
    segment: str
    action: str  # buy|avoid|watch
    direction: str  # bullish|bearish|neutral
    score: int  # 0..100
    confidence: float  # 0..1
    reasons: dict


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _compute_volume_spike(
    *,
    volumes: list[Optional[int]],
    window: int = 20,
    spike_ratio: float = 1.8,
) -> dict[str, Optional[float] | Optional[bool]]:
    vols = [float(v) for v in volumes if v is not None]
    if len(vols) < window + 1:
        return {"avg20": None, "latest": None, "ratio": None, "spike": None}
    latest = vols[-1]
    avg20 = sum(vols[-(window + 1) : -1]) / window
    ratio = (latest / avg20) if avg20 else None
    spike = bool(ratio is not None and ratio >= spike_ratio)
    return {"avg20": avg20, "latest": latest, "ratio": ratio, "spike": spike}


@dataclass(frozen=True)
class FreshSignalFeatures:
    ticker: str
    sc13_count: int
    sc13_latest_filed_at: Optional[str]

    insider_buy_value: float
    insider_sell_value: float
    insider_buy_count: int
    insider_sell_count: int
    insider_latest_event_date: Optional[str]

    trend: Optional[dict]
    trend_bullish_recent: bool
    trend_bearish_recent: bool

    volume: Optional[dict]
    volume_spike: bool

    context_13f: Optional[dict]


def score_fresh_signal_v0(*, features: FreshSignalFeatures, params: FreshSignalParams) -> FreshSignalRow:
    # Score components (0..100), centered at 50 (neutral).
    # This makes the number easier to interpret than a hard 0-based clamp for bearish signals.
    score = 50.0

    # SC13: high-signal, but infrequent.
    if features.sc13_count > 0:
        score += 45.0 + min(15.0, 5.0 * min(features.sc13_count, 3))

    # Insider: net buy/sell magnitude.
    net = features.insider_buy_value - features.insider_sell_value
    net_mag = log1p(abs(net) / 1_000_000.0) / log1p(100.0)  # ~0..1 for 0..$100M
    net_component = 25.0 * _clamp(net_mag, 0.0, 1.0)
    if net > 0:
        score += net_component
    elif net < 0:
        score -= net_component

    # Trend: timing.
    if features.trend_bullish_recent:
        score += 10.0
    elif features.trend_bearish_recent:
        score -= 10.0

    # Volume confirmation: only meaningful with trend direction.
    if features.volume_spike and features.trend_bullish_recent:
        score += 5.0
    elif features.volume_spike and features.trend_bearish_recent:
        score -= 5.0

    # Optional 13F context: tiny boost if it aligns, tiny penalty if it strongly contradicts.
    if features.context_13f is not None:
        delta = float(features.context_13f.get("delta_value_usd") or 0.0)
        if delta > 0:
            score += 5.0
        elif delta < 0:
            score -= 3.0

    score_i = int(round(_clamp(score, 0.0, 100.0)))

    # Direction + action
    direction = "neutral"
    if features.trend_bullish_recent or net > 0:
        direction = "bullish"
    if features.trend_bearish_recent or net < 0:
        direction = "bearish" if direction == "neutral" else direction

    has_fresh_event = (
        features.sc13_count > 0
        or features.insider_buy_value >= params.insider_min_value
        or features.insider_sell_value >= params.insider_min_value
    )
    action = "watch"
    if score_i >= params.buy_score_threshold and has_fresh_event and (features.trend_bullish_recent or net > 0):
        action = "buy"
    elif score_i <= params.avoid_score_threshold and has_fresh_event and (features.trend_bearish_recent or net < 0):
        action = "avoid"

    # Confidence (signal reliability, not profit probability)
    conf = 0.25
    if features.sc13_count > 0:
        conf += 0.25
    if features.insider_buy_value >= params.insider_min_value:
        conf += 0.20
    if features.insider_sell_value >= params.insider_min_value:
        conf += 0.10
    if features.trend is not None and (features.trend_bullish_recent or features.trend_bearish_recent):
        conf += 0.15
    if features.volume_spike:
        conf += 0.05
    if features.context_13f is not None:
        conf += 0.05

    # Penalize conflicting setup: strong fresh event but trend opposite.
    if features.sc13_count > 0 and features.trend_bearish_recent:
        conf -= 0.10
    if (features.insider_buy_value > features.insider_sell_value) and features.trend_bearish_recent:
        conf -= 0.05
    if (features.insider_sell_value > features.insider_buy_value) and features.trend_bullish_recent:
        conf -= 0.05

    conf_f = float(_clamp(conf, 0.10, 0.90))

    reasons = {
        "signal": "Fresh whale signals (SC13 + Form 4 + trend/volume)",
        "as_of": params.as_of.isoformat(),
        "fresh_days": params.fresh_days,
        "insider_min_value": params.insider_min_value,
        "sc13": {"count": features.sc13_count, "latest_filed_at": features.sc13_latest_filed_at},
        "insider": {
            "buy_value": features.insider_buy_value,
            "sell_value": features.insider_sell_value,
            "net_value": net,
            "buy_count": features.insider_buy_count,
            "sell_count": features.insider_sell_count,
            "latest_event_date": features.insider_latest_event_date,
        },
        "trend": features.trend,
        "trend_flags": {"bullish_recent": features.trend_bullish_recent, "bearish_recent": features.trend_bearish_recent},
        "volume": features.volume,
        "context_13f": features.context_13f,
    }

    return FreshSignalRow(
        ticker=features.ticker,
        segment="Fresh Whale Signals (SC13 + Insider + Trend)",
        action=action,
        direction=direction,
        score=score_i,
        confidence=conf_f,
        reasons=reasons,
    )


def compute_fresh_signals_v0(*, session: Session, params: FreshSignalParams) -> list[FreshSignalRow]:
    """
    "Fresh Whale Signals" snapshot:
    - Primary: SC 13D/13G (event-driven), Form 4 (event-driven)
    - Timing: price trend + volume confirmation
    - 13F is optional context only (delayed); used as a minor boost if present.
    """

    fresh_start = params.as_of - timedelta(days=params.fresh_days)

    # SC 13D/13G: event-driven corroborator
    sc13_rows = session.exec(
        select(
            LargeOwnerFiling.ticker,
            LargeOwnerFiling.source_accession,
            LargeOwnerFiling.form_type,
            LargeOwnerFiling.filer_name,
            LargeOwnerFiling.filed_at,
            LargeOwnerFiling.accepted_at,
        )
        .where(LargeOwnerFiling.filed_at != None)  # noqa: E711
        .where(LargeOwnerFiling.filed_at >= fresh_start)
    ).all()
    sc13_by_ticker: dict[str, dict] = {}
    sc13_details_by_ticker: dict[str, list[dict]] = {}
    for t, accession, form_type, filer_name, filed_at, accepted_at in sc13_rows:
        if not t:
            continue
        d = sc13_by_ticker.setdefault(t, {"count": 0, "latest_filed_at": None})
        d["count"] += 1
        if filed_at and (d["latest_filed_at"] is None or filed_at > d["latest_filed_at"]):
            d["latest_filed_at"] = filed_at
        sc13_details_by_ticker.setdefault(t, []).append(
            {
                "accession": accession,
                "form_type": form_type,
                "filer_name": filer_name,
                "filed_at": filed_at.isoformat() if filed_at else None,
                "accepted_at": accepted_at.isoformat() if accepted_at else None,
            }
        )

    # Form 4: P/S within freshness window (transaction date).
    # NOTE: many filings omit price; we estimate value using shares * (Form4 price or close price) when possible.
    insider_events = session.exec(
        select(
            InsiderTx.ticker,
            InsiderTx.transaction_code,
            InsiderTx.transaction_value,
            InsiderTx.shares,
            InsiderTx.price,
            InsiderTx.insider_name,
            InsiderTx.event_date,
            InsiderTx.filed_at,
            InsiderTx.source_accession,
        )
        .where(InsiderTx.event_date != None)  # noqa: E711
        .where(InsiderTx.event_date >= fresh_start)
        .where(col(InsiderTx.is_derivative) == False)  # noqa: E712
        .where(col(InsiderTx.transaction_code).in_(["P", "S"]))
    ).all()
    insider_events_by_ticker: dict[str, list[tuple]] = {}
    for row in insider_events:
        t = row[0]
        if not t:
            continue
        insider_events_by_ticker.setdefault(t, []).append(row)

    tickers = sorted(set(sc13_by_ticker.keys()) | set(insider_events_by_ticker.keys()))
    if not tickers:
        return []

    # Optional 13F context (delayed): latest 13f_whales snapshot mapped by ticker.
    whale_by_ticker: dict[str, dict] = {}
    whale_run = session.exec(
        select(SnapshotRun)
        .where(col(SnapshotRun.kind) == "13f_whales")
        .order_by(col(SnapshotRun.as_of).desc(), col(SnapshotRun.created_at).desc())
    ).first()
    if whale_run is not None:
        sec_rows = list(session.exec(select(Security).where(col(Security.ticker).in_(tickers))).all())
        cusips = [s.cusip for s in sec_rows if s.cusip]
        whales = (
            list(session.exec(select(Snapshot13FWhale).where(Snapshot13FWhale.run_id == whale_run.id, col(Snapshot13FWhale.cusip).in_(cusips))).all())
            if cusips
            else []
        )
        whale_by_cusip = {w.cusip: w for w in whales}
        for s in sec_rows:
            w = whale_by_cusip.get(s.cusip)
            if w is None:
                continue
            whale_by_ticker[s.ticker] = {
                "as_of": whale_run.as_of.isoformat(),
                "report_period": whale_run.params.get("report_period") if isinstance(whale_run.params, dict) else None,
                "previous_period": whale_run.params.get("previous_period") if isinstance(whale_run.params, dict) else None,
                "delta_value_usd": int(w.delta_value_usd),
                "total_value_usd": int(w.total_value_usd),
                "manager_count": int(w.manager_count),
                "manager_increase_count": int(w.manager_increase_count),
                "manager_decrease_count": int(w.manager_decrease_count),
            }

    out: list[FreshSignalRow] = []

    for t in tickers:
        sc13 = sc13_by_ticker.get(t, {"count": 0, "latest_filed_at": None})

        # Trend/volume (no lookahead): use bars <= as_of date.
        as_of_day = params.as_of.date().isoformat()
        bars = list(
            session.exec(
                select(PriceBar.date, PriceBar.close, PriceBar.volume)
                .where(PriceBar.ticker == t, PriceBar.source == "stooq", PriceBar.date <= as_of_day)
                .order_by(PriceBar.date)
            ).all()
        )
        trend_obj: Optional[dict] = None
        trend_bullish_recent = False
        trend_bearish_recent = False
        vol_obj: Optional[dict] = None
        if len(bars) >= 55:
            dates = [d for (d, _, _) in bars]
            closes = [float(c) for (_, c, _) in bars]
            vols = [v for (_, _, v) in bars]
            tm = compute_trend_from_closes(dates=dates, closes=closes)
            vol = _compute_volume_spike(volumes=vols)
            ret60 = None
            if len(closes) >= 61:
                prev = closes[-61]
                if prev:
                    ret60 = (closes[-1] / prev) - 1.0
            sma200 = None
            if len(closes) >= 200:
                sma200 = sum(closes[-200:]) / 200.0

            trend_obj = {
                "as_of_date": tm.as_of_date,
                "close": tm.close,
                "sma50": tm.sma50,
                "sma200": sma200,
                "return_20d": tm.return_20d,
                "return_60d": ret60,
                "bullish": tm.bullish,
            }
            vol_obj = vol
            close_by_date = {d: float(c) for (d, c, _) in bars}
            sorted_dates = [d for (d, _, _) in bars]

            # "recent" = last bar within 3 calendar days of as_of (weekends/holidays).
            is_recent = False
            if tm.as_of_date:
                try:
                    y, m, d = (int(x) for x in tm.as_of_date.split("-"))
                    last_day = datetime(y, m, d).date()
                    delta_days = (params.as_of.date() - last_day).days
                    is_recent = 0 <= delta_days <= 3
                except Exception:
                    is_recent = False

            if is_recent and tm.sma50 is not None and tm.return_20d is not None and tm.close is not None:
                trend_bullish_recent = tm.close > tm.sma50 and tm.return_20d > 0
                trend_bearish_recent = tm.close < tm.sma50 and tm.return_20d < 0
        else:
            close_by_date = {}
            sorted_dates = []

        def _close_on_or_before(day_s: str) -> Optional[float]:
            if day_s in close_by_date:
                return close_by_date[day_s]
            # Find the most recent prior date; bars are already <= as_of.
            for d in reversed(sorted_dates):
                if d <= day_s:
                    return close_by_date.get(d)
            return None

        # Insider aggregation for this ticker using estimated values when needed.
        buy_value = 0.0
        sell_value = 0.0
        buy_count = 0
        sell_count = 0
        latest_event_date: Optional[datetime] = None
        estimated_value_count = 0
        qualifying_txs: list[dict] = []

        for (_t, code, tx_value, shares, price, insider_name, event_dt, filed_at, source_accession) in insider_events_by_ticker.get(t, []):
            if event_dt is None:
                continue
            code_u = (code or "").upper().strip()
            if code_u not in {"P", "S"}:
                continue

            value = None
            estimated = False
            if tx_value is not None:
                value = float(tx_value)
            else:
                if shares is not None and price is not None:
                    value = float(shares) * float(price)
                    estimated_value_count += 1
                    estimated = True
                elif shares is not None:
                    day_s = event_dt.date().isoformat()
                    px = _close_on_or_before(day_s)
                    if px is not None:
                        value = float(shares) * float(px)
                        estimated_value_count += 1
                        estimated = True

            if value is None or value < params.insider_min_value:
                continue

            if code_u == "P":
                buy_value += value
                buy_count += 1
            else:
                sell_value += value
                sell_count += 1

            if latest_event_date is None or event_dt > latest_event_date:
                latest_event_date = event_dt
            qualifying_txs.append(
                {
                    "accession": source_accession,
                    "code": code_u,
                    "value": value,
                    "shares": float(shares) if shares is not None else None,
                    "price": float(price) if price is not None else None,
                    "estimated": estimated,
                    "insider_name": insider_name,
                    "event_date": event_dt.isoformat() if event_dt else None,
                    "filed_at": filed_at.isoformat() if filed_at else None,
                }
            )

        # If no qualifying events and no SC13, skip.
        sc13_count = int(sc13.get("count") or 0)
        if sc13_count == 0 and buy_count == 0 and sell_count == 0:
            continue

        vol_spike = bool(vol_obj and vol_obj.get("spike") is True)
        whale = whale_by_ticker.get(t)

        row = score_fresh_signal_v0(
            features=FreshSignalFeatures(
                ticker=t,
                sc13_count=sc13_count,
                sc13_latest_filed_at=(sc13.get("latest_filed_at").isoformat() if sc13.get("latest_filed_at") else None),
                insider_buy_value=buy_value,
                insider_sell_value=sell_value,
                insider_buy_count=buy_count,
                insider_sell_count=sell_count,
                insider_latest_event_date=(latest_event_date.isoformat() if latest_event_date else None),
                trend=trend_obj,
                trend_bullish_recent=trend_bullish_recent,
                trend_bearish_recent=trend_bearish_recent,
                volume=vol_obj,
                volume_spike=vol_spike,
                context_13f=whale,
            ),
            params=params,
        )
        # Add a tiny diagnostic for explainability.
        row.reasons["insider"]["estimated_value_count"] = estimated_value_count
        row.reasons["evidence"] = {
            "sc13_filings": sorted(sc13_details_by_ticker.get(t, []), key=lambda x: x.get("filed_at") or "", reverse=True)[:5],
            "insider_txs": sorted(qualifying_txs, key=lambda x: abs(float(x.get("value") or 0.0)), reverse=True)[:8],
        }
        out.append(row)

    return sorted(out, key=lambda r: (r.score, r.confidence), reverse=True)[: params.top_n]
