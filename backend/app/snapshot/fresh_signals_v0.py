from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import log1p
from typing import Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import InsiderTx, InsiderTxMeta, LargeOwnerFiling, PriceBar, Security, Snapshot13FWhale, SnapshotRun, SocialSignal
from app.settings import settings
from app.snapshot.market_regime import compute_market_regime
from app.snapshot.sector_regime import compute_sector_regimes
from app.snapshot.tech_guardrail_v0 import apply_tech_guardrail_v0
from app.snapshot.trend import compute_technical_snapshot_from_closes


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

    market: Optional[dict]

    sector: Optional[dict]

    insider_buy_value_10b5: float = 0.0
    insider_sell_value_10b5: float = 0.0
    insider_buy_count_10b5: int = 0
    insider_sell_count_10b5: int = 0
    insider_cluster_buy_insiders: int = 0
    social: Optional[dict] = None


def score_fresh_signal_v0(*, features: FreshSignalFeatures, params: FreshSignalParams) -> FreshSignalRow:
    # Score components (0..100), centered at 50 (neutral).
    # This makes the number easier to interpret than a hard 0-based clamp for bearish signals.
    score = 50.0

    # SC13: high-signal, but infrequent.
    if features.sc13_count > 0:
        score += 45.0 + min(15.0, 5.0 * min(features.sc13_count, 3))

    # Insider: net buy/sell magnitude.
    # Discretionary transactions carry full weight; 10b5-1 (scheduled) carry reduced weight.
    net = (features.insider_buy_value - features.insider_sell_value) + 0.20 * (
        features.insider_buy_value_10b5 - features.insider_sell_value_10b5
    )
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

    # Market regime (small additive): de-risk in bearish tape, slight boost in bullish tape.
    market_score_adj = 0.0
    if features.market is not None:
        if features.market.get("bearish_recent"):
            market_score_adj = -2.0
        elif features.market.get("bullish_recent"):
            market_score_adj = +1.0
    score += market_score_adj

    # Sector regime (optional): only applied when the ticker has a sector ETF mapping.
    sector_score_adj = 0.0
    if features.sector is not None:
        if features.sector.get("bearish_recent"):
            sector_score_adj = -1.0
        elif features.sector.get("bullish_recent"):
            sector_score_adj = +1.0
    score += sector_score_adj

    # Social listener (optional, feature-flagged): cashtag velocity with persistence.
    social_score_adj = 0.0
    social_conf_adj = 0.0
    if features.social and bool(features.social.get("enabled")):
        velocity = float(features.social.get("velocity") or 0.0)
        persistent = bool(features.social.get("persistent"))
        mentions_latest = int(features.social.get("mentions_latest") or 0)
        min_mentions = int(features.social.get("min_mentions") or 0)
        sentiment_hint = features.social.get("sentiment_hint")
        sentiment = float(sentiment_hint) if sentiment_hint is not None else None
        if persistent and velocity >= float(features.social.get("velocity_threshold") or 0.0) and mentions_latest >= min_mentions:
            if sentiment is None or sentiment >= 0:
                social_score_adj = +4.0
                social_conf_adj = +0.04
            else:
                social_score_adj = -4.0
                social_conf_adj = -0.04
        elif velocity >= float(features.social.get("velocity_threshold") or 0.0) and mentions_latest >= min_mentions:
            # One-window spike: weaker confidence effect than a persistent spike.
            social_score_adj = +1.0 if (sentiment is None or sentiment >= 0) else -1.0
            social_conf_adj = -0.01
    score += social_score_adj

    score_i = int(round(_clamp(score, 0.0, 100.0)))
    tg = apply_tech_guardrail_v0(score=score_i, tech=features.trend)
    score_i = tg.score_after

    # Cluster discretionary buys are a higher-quality insider signal.
    if features.insider_cluster_buy_insiders >= 3 and features.insider_buy_value >= params.insider_min_value:
        score_i = int(round(_clamp(float(score_i) + 5.0, 0.0, 100.0)))

    conviction_1_10 = int((score_i + 9) // 10)

    # Direction + action
    direction = "neutral"
    if features.trend_bullish_recent or net > 0:
        direction = "bullish"
    if features.trend_bearish_recent or net < 0:
        direction = "bearish" if direction == "neutral" else direction

    insider_dir = "neutral"
    if net > 0:
        insider_dir = "bullish"
    elif net < 0:
        insider_dir = "bearish"
    trend_dir = "bullish" if features.trend_bullish_recent else ("bearish" if features.trend_bearish_recent else "neutral")

    divergence_score_adj = 0
    divergence_conf_adj = 0.0
    divergence_label = "none"
    divergence_note = "signals are neutral/mixed"
    if insider_dir == "bullish" and trend_dir == "bearish":
        divergence_label = "bullish_divergence"
        divergence_note = "insider accumulation while trend is bearish"
        divergence_score_adj = +3
        divergence_conf_adj = -0.03
    elif insider_dir == "bearish" and trend_dir == "bullish":
        divergence_label = "bearish_divergence"
        divergence_note = "insider selling against bullish trend"
        divergence_score_adj = -8
        divergence_conf_adj = -0.08
    elif features.sc13_count > 0 and trend_dir == "bearish":
        divergence_label = "sc13_trend_conflict"
        divergence_note = "SC13 filing present but price trend is bearish"
        divergence_score_adj = -4
        divergence_conf_adj = -0.06
    elif insider_dir != "neutral" and insider_dir == trend_dir:
        divergence_label = "alignment"
        divergence_note = "insider flow and trend are aligned"
        divergence_score_adj = +1
        divergence_conf_adj = +0.02

    if divergence_score_adj != 0:
        score_i = int(round(_clamp(float(score_i + divergence_score_adj), 0.0, 100.0)))

    has_fresh_event = (
        features.sc13_count > 0
        or features.insider_buy_value >= params.insider_min_value
        or features.insider_sell_value >= params.insider_min_value
        or features.insider_buy_value_10b5 >= params.insider_min_value
        or features.insider_sell_value_10b5 >= params.insider_min_value
    )
    action = "watch"
    # BUY should prefer discretionary signals; 10b5-1-only setups should rarely upgrade to BUY.
    strong_insider_buy = features.insider_buy_value >= params.insider_min_value
    if score_i >= params.buy_score_threshold and has_fresh_event and (features.trend_bullish_recent or net > 0) and (
        features.sc13_count > 0 or strong_insider_buy or features.trend_bullish_recent or net > 0
    ):
        action = "buy"
    elif score_i <= params.avoid_score_threshold and has_fresh_event and (
        features.trend_bearish_recent or (net < 0 and not features.trend_bullish_recent)
    ):
        action = "avoid"
    elif divergence_label == "bearish_divergence" and score_i <= (params.avoid_score_threshold + 5):
        # Escalate risk classification when insider flow strongly contradicts bullish price trend.
        action = "avoid"

    # Confidence (signal reliability, not profit probability)
    conf = 0.25
    if features.sc13_count > 0:
        conf += 0.25
    if features.insider_buy_value >= params.insider_min_value:
        conf += 0.20
    elif features.insider_buy_value_10b5 >= params.insider_min_value:
        conf += 0.05
    if features.insider_sell_value >= params.insider_min_value:
        conf += 0.10
    elif features.insider_sell_value_10b5 >= params.insider_min_value:
        conf += 0.02
    if features.insider_cluster_buy_insiders >= 3 and features.insider_buy_value >= params.insider_min_value:
        conf += 0.15
    if features.trend is not None and (features.trend_bullish_recent or features.trend_bearish_recent):
        conf += 0.15
    if features.volume_spike:
        conf += 0.05
    if features.context_13f is not None:
        conf += 0.05

    # Market regime confidence adjustment (small): bearish tape reduces conviction.
    market_conf_adj = 0.0
    if features.market is not None:
        if features.market.get("bearish_recent"):
            market_conf_adj = -0.05
        elif features.market.get("bullish_recent"):
            market_conf_adj = +0.02
    conf += market_conf_adj

    sector_conf_adj = 0.0
    if features.sector is not None:
        if features.sector.get("bearish_recent"):
            sector_conf_adj = -0.02
        elif features.sector.get("bullish_recent"):
            sector_conf_adj = +0.01
    conf += sector_conf_adj
    conf += social_conf_adj

    conf += divergence_conf_adj

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
            "buy_value_10b5": features.insider_buy_value_10b5,
            "sell_value_10b5": features.insider_sell_value_10b5,
            "buy_count_10b5": features.insider_buy_count_10b5,
            "sell_count_10b5": features.insider_sell_count_10b5,
            "cluster_buy_insiders": features.insider_cluster_buy_insiders,
            "latest_event_date": features.insider_latest_event_date,
        },
        "insider_quality_policy": {
            "codes_high_signal": ["P", "S"],
            "codes_ignored": ["A", "M", "G"],
            "planned_trade_weight": 0.20,
            "cluster_buy_rule": ">=3 distinct insiders with discretionary P in fresh window",
        },
        "trend": features.trend,
        "trend_flags": {"bullish_recent": features.trend_bullish_recent, "bearish_recent": features.trend_bearish_recent},
        "tech_guardrail": {
            "ft": tg.ft,
            "adj": tg.adj,
            "score_before": tg.score_before,
            "score_after": tg.score_after,
            "notes": tg.notes,
        },
        "volume": features.volume,
        "context_13f": features.context_13f,
        "market": features.market,
        "market_adjustment": {"score": market_score_adj, "confidence": market_conf_adj},
        "sector": features.sector,
        "sector_adjustment": {"score": sector_score_adj, "confidence": sector_conf_adj},
        "social": features.social,
        "social_adjustment": {"score": social_score_adj, "confidence": social_conf_adj},
        "divergence": {
            "label": divergence_label,
            "insider_direction": insider_dir,
            "trend_direction": trend_dir,
            "score_adjustment": divergence_score_adj,
            "confidence_adjustment": divergence_conf_adj,
            "note": divergence_note,
        },
        "conviction_1_10": conviction_1_10,
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
            InsiderTx.insider_cik,
            InsiderTxMeta.is_10b5_1,
            InsiderTx.event_date,
            InsiderTx.filed_at,
            InsiderTx.source_accession,
        )
        .join(InsiderTxMeta, col(InsiderTxMeta.insider_tx_id) == col(InsiderTx.id), isouter=True)
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

    # Optional social listener (feature-flagged): cashtag bucket velocity + persistence.
    social_by_ticker: dict[str, dict] = {}
    if settings.social_enabled:
        social_start = params.as_of - timedelta(days=7)
        social_rows = list(
            session.exec(
                select(
                    SocialSignal.ticker,
                    SocialSignal.bucket_start,
                    SocialSignal.mentions,
                    SocialSignal.sentiment_hint,
                    SocialSignal.source,
                )
                .where(col(SocialSignal.ticker).in_(tickers))
                .where(col(SocialSignal.bucket_start) >= social_start)
                .where(col(SocialSignal.bucket_start) <= params.as_of)
                .order_by(col(SocialSignal.ticker), col(SocialSignal.bucket_start).desc())
            ).all()
        )
        grouped: dict[str, list[tuple]] = {}
        for row in social_rows:
            grouped.setdefault(str(row[0]).upper(), []).append(row)
        for t, rows in grouped.items():
            if not rows:
                continue
            latest_mentions = int(rows[0][2] or 0)
            latest_bucket = rows[0][1]
            latest_sentiment = rows[0][3]
            source = rows[0][4]
            prev_mentions = [int(r[2] or 0) for r in rows[1:]]
            baseline = (sum(prev_mentions) / len(prev_mentions)) if prev_mentions else None
            velocity = (latest_mentions / baseline) if (baseline and baseline > 0) else None
            # Two-window persistence rule: latest and previous bucket both above threshold.
            threshold = float(settings.social_velocity_threshold)
            persistent = False
            if baseline and baseline > 0 and len(rows) >= 2:
                m0 = int(rows[0][2] or 0)
                m1 = int(rows[1][2] or 0)
                persistent = (m0 >= threshold * baseline) and (m1 >= threshold * baseline)
            social_by_ticker[t] = {
                "enabled": True,
                "source": source,
                "latest_bucket_start": latest_bucket.isoformat() if latest_bucket else None,
                "mentions_latest": latest_mentions,
                "mentions_baseline_7d": baseline,
                "velocity": velocity,
                "persistent": persistent,
                "sentiment_hint": float(latest_sentiment) if latest_sentiment is not None else None,
                "velocity_threshold": threshold,
                "min_mentions": int(settings.social_min_mentions),
            }

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
    market = compute_market_regime(session=session, as_of=params.as_of, ticker="SPY")
    sector_regimes = compute_sector_regimes(session=session, as_of=params.as_of)
    # Optional per-ticker mapping (admin setting). Keep empty by default.
    from app.admin_settings import get_setting

    ticker_sector_map = get_setting(session, "ticker_sector_etf_map_v0") or {}

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
            vol = _compute_volume_spike(volumes=vols)
            trend_obj = compute_technical_snapshot_from_closes(dates=dates, closes=closes)
            vol_obj = vol
            close_by_date = {d: float(c) for (d, c, _) in bars}
            sorted_dates = [d for (d, _, _) in bars]

            # "recent" = last bar within 3 calendar days of as_of (weekends/holidays).
            is_recent = False
            if trend_obj.get("as_of_date"):
                try:
                    y, m, d = (int(x) for x in str(trend_obj.get("as_of_date")).split("-"))
                    last_day = datetime(y, m, d).date()
                    delta_days = (params.as_of.date() - last_day).days
                    is_recent = 0 <= delta_days <= 3
                except Exception:
                    is_recent = False

            if is_recent and trend_obj.get("sma50") is not None and trend_obj.get("return_20d") is not None and trend_obj.get("close") is not None:
                c = float(trend_obj["close"])
                s50 = float(trend_obj["sma50"])
                r20 = float(trend_obj["return_20d"])
                trend_bullish_recent = c > s50 and r20 > 0
                trend_bearish_recent = c < s50 and r20 < 0
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
        buy_value_10b5 = 0.0
        sell_value_10b5 = 0.0
        buy_count_10b5 = 0
        sell_count_10b5 = 0
        cluster_buy_insiders: set[str] = set()
        latest_event_date: Optional[datetime] = None
        estimated_value_count = 0
        qualifying_txs: list[dict] = []

        for (
            _t,
            code,
            tx_value,
            shares,
            price,
            insider_name,
            insider_cik,
            is_10b5_1,
            event_dt,
            filed_at,
            source_accession,
        ) in insider_events_by_ticker.get(t, []):
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

            is_10b5 = bool(is_10b5_1) if is_10b5_1 is not None else False
            if code_u == "P":
                if is_10b5:
                    buy_value_10b5 += value
                    buy_count_10b5 += 1
                else:
                    buy_value += value
                    buy_count += 1
                    if insider_cik:
                        cluster_buy_insiders.add(str(insider_cik))
                    elif insider_name:
                        cluster_buy_insiders.add(str(insider_name))
            else:
                if is_10b5:
                    sell_value_10b5 += value
                    sell_count_10b5 += 1
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
                    "insider_cik": insider_cik,
                    "is_10b5_1": is_10b5_1,
                    "event_date": event_dt.isoformat() if event_dt else None,
                    "filed_at": filed_at.isoformat() if filed_at else None,
                }
            )

        # If no qualifying events and no SC13, skip.
        sc13_count = int(sc13.get("count") or 0)
        if sc13_count == 0 and (buy_count + sell_count + buy_count_10b5 + sell_count_10b5) == 0:
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
                insider_buy_value_10b5=buy_value_10b5,
                insider_sell_value_10b5=sell_value_10b5,
                insider_buy_count_10b5=buy_count_10b5,
                insider_sell_count_10b5=sell_count_10b5,
                insider_cluster_buy_insiders=len(cluster_buy_insiders),
                social=social_by_ticker.get(str(t).upper()),
                trend=trend_obj,
                trend_bullish_recent=trend_bullish_recent,
                trend_bearish_recent=trend_bearish_recent,
                volume=vol_obj,
                volume_spike=vol_spike,
                context_13f=whale,
                market=market,
                sector=(
                    sector_regimes.get(ticker_sector_map.get(t))
                    if isinstance(ticker_sector_map, dict) and isinstance(ticker_sector_map.get(t), str)
                    else None
                ),
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
