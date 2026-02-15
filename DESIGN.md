# WealthPulse — Blueprint Design

## Goal
Generate explainable **Buy/Sell/Watch** recommendations by combining “big money” signals (institutions/insiders/large owners), market behavior, and news/catalysts; expose results via:
- **Admin dashboard** (only you).
- **Daily subscriber alerts** (no dashboard access).

## Non-goals (for v0)
- Personalized portfolios or per-user risk profiles.
- Real-time trading execution.
- Complex ML as a requirement (start with explainable scoring; evolve later).

## Roles & Access
- `admin`: full dashboard + tools + config.
- `subscriber`: alerts only.

### Admin authentication (pilot)
If `WEALTHPULSE_ADMIN_PASSWORD` is set, all `/admin/*` endpoints require an **Authorization Bearer token** obtained via the login page.

## Subscriber alerts (v0 pilot)
Subscribers do not access the dashboard. They receive a daily email (weekdays) containing up to 5 **BUY/SELL** signals.

### Manual-only send (admin review)
Alert **generation is automatic** (a daily draft is created for review), but **sending is manual**:
- Admin reviews the generated alert items on the **Latest** dashboard.
- Admin can **Send** individual alert items or **Send All**.
- A manual “Generate Draft” option still exists in **Runs** for ad-hoc regeneration.

### Email delivery (pilot)
- Provider: **SMTP** (Gmail + App Password recommended for quick pilot testing).
- Subscription flow: **double opt-in**
  - `POST /subscribe { email }` → sends confirmation email
  - `GET /confirm?token=...` → activates subscriber
  - `GET /unsubscribe?token=...` → unsubscribes

### Audit artifacts
Every daily send produces an auditable, replayable artifact in SQLite:
- `alert_runs` (as_of + policy + source snapshot run ids)
- `alert_items` (selected tickers, BUY/SELL only, why + evidence)
- `alert_deliveries` (per-subscriber delivery status)

### Noise control (v0)
Subscriber sends are **diff-gated**: if a draft run’s items are identical to the previous finalized run, the “Send All” operation marks the run as `skipped` and does not email.

### Run lifecycle (v0)
`alert_runs.status` is:
- `draft`: generated for admin review (no email sent)
- `sent`: email deliveries attempted
- `skipped`: send was suppressed due to diff-gating (no deliveries created)


## v0 Technical Architecture (local-first, minimal)
Goal: prove dashboard value with the fewest moving parts.

- Frontend (admin-only): **React SPA (Vite)**
- Backend: **Python + FastAPI** (single app: API + scheduled jobs)
- Database: **SQLite** (v0)
- Scheduler: run from the backend in dev; production can use a simple cron later
- No Redis/queues/microservices in v0

## Deployment (v0)
Cloud-agnostic v0 deployment uses:
- One VM + Docker Compose
- Containers: `web` (reverse proxy + static UI), `backend` (FastAPI), `db` (Postgres)
- Only port **80** is public in the IP-only pilot (domain/TLS later)
- Backend is private; all API calls go through `/api/*`

### Local dev constraints
- Optimized for low CPU/RAM: one backend process + one frontend dev server + SQLite.
- All computations produce an auditable daily snapshot so results are reproducible.

## Dashboard (layout target)
Dashboard matches “segments + tables + feed” style:
- **Top row: Segments/Themes** (buckets with 2–5 picks each)
- **Bottom-left: Top movers** (1D/1W gainers/losers)
- **Bottom-middle: Top picks** (global ranked list)
- **Bottom-right: Insider activity** feed (Form 4 first; optionally other filings later)
- Click any stock → **Detail drawer** with evidence timeline, score breakdown, and invalidation/risk notes.

## Initial segment set (v0)
Signal-based buckets to ensure the dashboard stays populated:
- Insider Activity (Form 4)
- Activist / Large Owner (13D/13G)
- Institutional Accumulation (13F)
- Catalyst / News
- Momentum / Trend
- Risk / Avoid (Sell/Short Watch)

## Explainability Requirements (hard rule)
Every recommendation must be backed by:
- `as_of` time (when the recommendation was computed)
- Evidence timeline (events + sources + dates)
- Score breakdown (which signals contributed and by how much)
- Confidence + data freshness/lag indicators
- “Invalidations” (what would change/downgrade the recommendation)

## Scoring (v0 implemented)
We currently implement a **v0 scoring system** that separates:
- **Whale conviction (context):** institutional accumulation derived from **13F quarter-over-quarter deltas**.
- **Timing corroborators:** fresher signals used to upgrade `watch` → `buy` and to adjust the final score.

### Fresh Whale Signals (v0 implemented)
In addition to 13F-based Top Picks, we compute a separate **Fresh Whale Signals** snapshot that is driven by:
- **SC 13D/13G filings** (event-driven)
- **Form 4 insider buys/sells** above a minimum value (event-driven)
- **Trend + volume** (timing/confirmation)

This snapshot is designed for “what’s happening recently”, while 13F remains delayed context.

### Avoid labeling in Fresh Whale Signals (v0)
We keep AVOID conservative:
- Insider selling can flag risk, but a **bullish trend** should generally prevent an automatic `avoid` label.
- v0 rule: `avoid` requires **bearish trend**, or **net insider sell while trend is not bullish**.

### 13F “whale” score (context)
Computed from the latest stored 13F delta snapshot (`snapshot_13f_whales`):
- Magnitude (rank-based): higher QoQ delta ranks higher
- Breadth: fraction of managers increasing (`manager_increase_count / manager_count`)
- Size: log-scaled `total_value_usd`
- Penalties:
  - Low mapping coverage (CUSIP→ticker)
  - Small sample size (low manager_count)

The stored recommendation payload includes a `score_breakdown` block so the UI can render component scores.

### Trend corroborator (timing)
We ingest daily closes (currently from **Stooq**) and compute a simple trend corroborator:
- **Bullish if:** `close > SMA50` AND `20D return > 0`
- “Recent” if last available bar date is within ~3 calendar days of the recommendation `as_of` timestamp.

Trend is used in two ways:
1) **Corroborator gating:** if score ≥ threshold and trend is bullish recent, a pick may upgrade to `buy`.
2) **Score adjustment:** the final score is `whale_score + trend_adjustment` (clamped 0–100), where:
   - bullish trend: `trend_adjustment = +8`
   - trend data exists but not bullish: `trend_adjustment = -8`

### Corroborator gating (watch → buy)
Because **13F is delayed**, the v0 action rule defaults to `watch`.
It upgrades to `buy` only when:
- `score >= buy_score_threshold` AND at least one **fresh corroborator** exists within `fresh_days`:
  - Schedule 13D/13G filing (`sc13_recent`)
  - Insider buy (Form 4) above `insider_min_value` (`insider_buy_recent`)
  - Bullish trend (`trend_bullish_recent`)

Corroborator flags and parameters are stored in `reasons.corroborators` for explainability.


## Freshness & timeframe (critical)
The dashboard must prevent “2-year-old data” from being presented as a “buy now” justification.

### Always show dates (no ambiguity)
For each evidence item, store and display:
- `event_date`: when the transaction/position change occurred (if known)
- `filed_at`: when it was reported (SEC filing timestamp, publish time)
- `detected_at`: when we ingested/parsed it
- `age`: how old it is at the snapshot `as_of`

### Freshness policy (v0)
- **Hard gate:** do not recommend a **Buy/Sell** unless at least one **recent** high-signal event exists.
- **Default definition of “recent”:** **7 calendar days** (configurable).
- **Recency decay:** older evidence contributes less to score, even if it remains visible in the timeline.
- **Stale-source labeling:** sources with inherent delay must be labeled and down-weighted (especially 13F).

### Filing-specific guidance (v0)
- **Form 4 (insiders):** high signal; require recency (**7 days**) for Buy/Sell.
- **13D/13G:** high signal but may persist; allow older events to remain visible, but require at least one **7-day** corroborator (trend/catalyst/insider) for “buy now”.
- **13F:** **not real-time** (quarterly, delayed). Treat as “institutional accumulation” context; never present as “just bought today”.

### Market trends (v0)
Compute and show trends at three levels, all at the same snapshot `as_of`:
- **Market trend:** broad index proxy (e.g., SPY/QQQ equivalent for the chosen universe)
- **Sector trend:** sector/industry aggregation
- **Stock trend:** per ticker

Keep trends simple and consistent:
- Display 1D / 1W / 1M returns and a regime label (Up/Down/Sideways) derived from explicit rules.

## Core Architecture (modular monolith first)
Keep internal boundaries strict to remain testable and allow future service extraction.

### Modules (suggested)
1) **Connectors**: fetch filings/prices/news/vendor data.
2) **Normalization**: validate, dedupe, map into canonical schemas.
3) **Event Store**: unified stream of normalized events (filings/news/market events).
4) **Signals/Features**: compute interpretable signals from events.
5) **Scoring & Recommendations**: combine signals → score → action + explanation.
6) **Segmentation**: assign each stock to exactly one primary segment for UI/alerts.
7) **API**: dashboard endpoints + subscriber alert endpoints.
8) **Alerts**: daily snapshot diff + message composition + delivery (email/SMS/push later).
9) **Admin Tools**: segment priority, thresholds, allow/deny lists, audit.

## Data Layers (reliability + audit)
- **Raw immutable store**: store original filings/news payloads for replay and audit.
- **Normalized relational store**: canonical entities (stocks, investors, filings, events).
- **Analytics/time-series store** (optional early): fast queries for movers, backtests, screens.

## Signal Tiers (recommended starting order)
Tier A (high confidence):
- **Form 4**: insider buys/sells (transaction-level, frequent)
- **13D/13G**: large owner stakes / activist entry (high signal)

Tier B (delayed but useful):
- **13F**: institutional positions and increases (quarterly; treat as “accumulation” not real-time)

Tier C (optional later; often vendor-dependent):
- “Unusual block trades” / prints (requires specialized market data); v0 can approximate with volume/price-impact heuristics.

## Segments/Themes: “one stock, one segment”
Internally, a stock may qualify for multiple segments; externally, show exactly one.

### Primary segment selection
Use **fixed priority + score tiebreaker + stability**:
1) Insider Activity (Form 4)
2) Activist / Large-owner entry (13D/13G)
3) Institutional Accumulation (13F)
4) Catalyst / News-driven
5) Momentum / Trend
6) Value / Quality (optional later)

**Tiebreaker:** within the same priority tier, choose the segment with the highest segment-specific contribution score.

**Stability rule:** keep yesterday’s primary segment unless:
- current segment becomes ineligible, OR
- a higher-priority segment becomes eligible, OR
- a same/higher-priority segment exceeds by a material margin (configurable; start with +10 points).

## Recommendation Output (conceptual contract)
For each recommended stock:
- `ticker`, `name`, `price`
- `action`: buy | sell | watch
- `score`: 0–100
- `confidence`: 0–1
- `segment`: primary segment/theme
- `horizon`: short | swing | long (start with swing unless configured)
- `reasons[]`: short bullet reasons (for cards/alerts)
- `risk_flags[]`: liquidity, volatility, dilution, earnings risk, etc.
- `evidence_refs[]`: IDs/links to timeline events
- `as_of`

## Daily Snapshot (source of truth for UI + alerts)
Compute once per day (configurable time) to produce:
- Segment buckets
- Global top picks
- Movers table
- Insider activity feed
- Per-stock detail payloads

Subscribers receive alerts derived from the same snapshot + diffs from the prior day (only material changes).

### Daily alert packaging (v0)
- Send **up to 5** tickers per day.
- Include **Buy/Sell only** (omit Watch in subscriber notifications for now).
- Alert selection should favor: higher confidence, fresher evidence, and diversified risk (optional constraint).

### Alert delivery (v0)
- Channel: **Email only**.
- Keep content minimal; iterate later (e.g., add SMS/push, richer rationale, personalization).
- Schedule: **Weekdays at 8:30 AM CST**.

### Daily run timing (v0)
- Run the daily snapshot compute shortly before send (e.g., **8:15 AM CST weekdays**) so the email is based on the latest available data.
- Treat this as configurable; v0 only needs one schedule.

## Testing Strategy (design-level)
- Unit tests: signal calculations, scoring rules, segment selection stability.
- Integration tests: connector → normalization → event store (idempotency + dedupe).
- Replay tests: re-run scoring from raw store for auditability.
- Golden tests: deterministic snapshot output for a fixed historical date range.

## Accuracy & Quality Gates (critical)
The dashboard is the product. Everything else (alerts, subscriptions, channels) is downstream of the same snapshot, so we need explicit quality gates.

### Data correctness
- **Source-of-truth fields:** always store both `event_date` (transaction) and `filed_at` (when reported).
- **Normalization guarantees:** canonical ticker mapping, currency/units normalization, and stable IDs for filings/events.
- **Idempotency + dedupe:** prevent double-counting events (especially re-parses and backfills).
- **Freshness checks:** track staleness per source; surface warnings on the dashboard when data is delayed.

### Recommendation correctness (evaluation)
- **Backtest harness (basic):** for each historical snapshot date, compute recommendations and evaluate forward returns over fixed horizons (e.g., 5D/20D) and versus baseline (SPY/sector ETF).
- **Segment-level reporting:** accuracy is measured per segment (Insider/13D/13F/etc.), not just globally.
- **Calibration checks:** confidence buckets should correspond to observed hit rates over time (even if rough at first).

### Operational quality
- **Fail closed:** if a critical feed is stale, degrade output (fewer picks) and flag it; avoid confidently wrong results.
- **Audit trail:** every dashboard item must be reproducible from stored evidence + versioned scoring config.

## Observability (minimum)
- Per-run metrics: freshness/lag by data source, counts of events ingested, errors, dedup rate.
- Audit log: for each recommendation, store inputs, derived signals, and final score.
