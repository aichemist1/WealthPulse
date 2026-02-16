# WealthPulse — Decisions Log (Pause/Resume Context)

Record decisions here so we can resume without re-deriving context.

## 2026-02-11
- Tech stack (v0): **React SPA (Vite)** admin dashboard, **Python/FastAPI** backend, **SQLite** DB, minimal scheduler.
- Product access: **Admin dashboard only**; **subscribers receive notifications only** (no dashboard access).
- Dashboard style target: segments/themes buckets + top movers + top picks + insider activity feed + stock detail drill-down.
- Segments display rule: **one stock shown in one segment** (no duplication).
- Primary segment selection: **fixed priority + score tiebreaker + stability rule**.
- Segment priority (v0):
  1) Insider Activity (Form 4)
  2) Activist / Large-owner entry (13D/13G)
  3) Institutional Accumulation (13F)
  4) Catalyst / News-driven
  5) Momentum / Trend
  6) Value / Quality (optional later)
- Initial segment set (v0):
  - Insider Activity
  - Activist / Large Owner
  - Institutional Accumulation
  - Catalyst / News
  - Momentum / Trend
  - Risk / Avoid (Sell/Short Watch)
- Subscriber daily alerts (v0): **max 5 tickers/day**, **Buy/Sell only** (omit Watch).
- Delivery channel (v0): **Email only**.
- Daily schedule (v0): **Weekdays at 8:30 AM CST** (compute shortly before send).
- Trend coverage goal: show **market**, **sector**, and **stock** trends (as-of snapshot time).
- Freshness requirement: recommendations must not rely on stale “whale” evidence (e.g., 2024 holdings) as a “buy now” justification; always show `event_date` vs `filed_at`, and apply recency gating/decay (13F treated as delayed context).
- Freshness gate (v0): require at least one **high-signal corroborator within 7 calendar days** for Buy/Sell.
- Signal sources under consideration: **13F increases**, **13D/13G**, and “unusual block trades”.
  - Recommended approach: start with Tier A (Form 4, 13D/13G), add Tier B (13F), then Tier C (block trades) later.

## 2026-02-11 — Implementation status
- Backend scaffold added under `backend/`:
  - FastAPI app with `/health` and `/admin/stocks` endpoints.
  - SQLite/SQLModel models for `RawPayload`, `Stock`, `Investor`, `Filing`, `Event`, `InsiderTx` with uniqueness constraints for dedupe/idempotency.
  - CLI (`python -m app.cli`) supports:
    - `init-db`
    - `ingest-form4-xml` (dev-only local XML ingestion)
    - `ingest-form4-edgar` (daily index → fetch filing → extract ownership XML → normalize)
    - `ingest-13f-edgar` (daily index → fetch 13F submission → extract information table → normalize holdings)
    - `snapshot-13f-whales` (quarter-over-quarter deltas by CUSIP)
    - `snapshot-recommendations-v0` (creates v0 scored Top Picks from latest 13F snapshot; currently outputs Watch only)
  - Minimal Form 4 XML parser + EDGAR daily index parsing + filing XML extraction tests.
  - 13F information table XML parser + 13F ingestion/snapshot logic.
- Local verification performed:
  - `pytest` passes for parser/index/extraction tests.
  - CLI smoke tested against temp SQLite DB (init + ingest + query).
  - Live SEC fetch validated for 13F on 2025-11-14 (daily index + filing fetch + info table parse + holdings insert).
  - API routes verified via FastAPI TestClient (socket bind via `uvicorn` not permitted in this sandbox).
  - Demo UI validated locally with real SEC 13F sample data and OpenFIGI enrichment; Top Picks drawer shows score breakdown + evidence context.

## Open questions
- Segment list: final names + what “high_potential” means operationally.
- Daily run schedule: compute time + alert time + timezone.
- Alert channel for MVP: email only vs SMS/push as well.
- Data vendors: prices/news/block trades (if any) and budget constraints.
- 13F mapping: 13F holdings are CUSIP-based; decide how to map CUSIP → ticker (vendor dataset vs internal mapping file).
  - Current bootstrap plan: use OpenFIGI enrichment (CUSIP→ticker) and/or a public S&P 500 CSV ticker list; replace with paid security master + official membership later.
- Recommendation gating: Buy/Sell should require corroborators (13D/13G, Form 4, trend/news) within freshness window; v0 recommendations remain Watch-only.

## 2026-02-11 — Scoring/gating updates
- v0 recommendations now store `whale_score` (13F-only context) plus `trend_adjustment` and produce a final `score = whale_score + trend_adjustment` (clamped 0–100).
- Trend corroborator is based on daily closes (Stooq) with rule: `close > SMA50` AND `20D return > 0`, treated as “recent” if last bar within ~3 calendar days of `as_of`.
- `watch → buy` gating now allows a BUY when `score >= buy_score_threshold` AND at least one corroborator is fresh: SC13, insider buy ≥ `insider_min_value`, or bullish trend.

## 2026-02-11 — Dashboard UX updates
- Admin UI split into two tabs:
  - **Latest**: “intelligent” cards only (Top Picks + Insider Whale Buys).
  - **Runs**: validation/debug cards (coverage + snapshot run browser + raw 13F whale deltas by run).
- Top Picks now supports a **detail drawer** (click a row) showing:
  - Evidence dates (`report_period`, `previous_period`) and 13F delta metrics
  - Corroborators (SC13 / insider / trend) and freshness window
  - Trend metrics (close, SMA50, 20D return, trend as-of date)
  - Score breakdown (magnitude/breadth/size/penalties + whale_score + trend_adjustment)

## 2026-02-11 — Fresh Whale Signals (v0)
- Added a new snapshot kind: `fresh_signals_v0` that ranks tickers primarily using **SC 13D/13G + Form 4** within a freshness window.
- Uses **trend + volume spike** as timing/confirmation.
- 13F is included only as optional context (small score/confidence boost if aligned), not as the primary driver.
- UI: new “Fresh Whale Signals (v0)” card on **Latest** with a shared detail drawer.
- UI: added “Avoid / Risk (v0)” card derived from Fresh Whale Signals rows labeled `avoid`.

## 2026-02-12 — Dashboard watchlists
- Added two curated watchlist cards to the Latest dashboard:
  - **ETF / Macro Plays** (seed tickers: GLD, AIQ, QTUM, SKYY, MAGS, JTEK, ARKW, CHAT, HACK)
  - **High-Yield Dividend Stocks** (seed tickers: VNOM, SLB, EOG)
- Data source (v0): Stooq price bars; shows close, 20D/60D returns, SMA50/SMA200, and a simple trend label.
- Dividend yield data is not integrated yet; the “High-Yield” list is curated manually for now.
- UX: watchlist rows are clickable and open a small detail drawer (SMA50/SMA200, 20D/60D returns, and volume ratio).

## 2026-02-12 — Dividend fundamentals (v0)
- Added best-effort dividend fundamentals fetch via Yahoo Finance (unofficial endpoint) for the dividend watchlist:
  - `dividend_yield_ttm`, `payout_ratio`, `ex_dividend_date`
- Surface these fields in the High-Yield Dividend Stocks card + drawer.

## 2026-02-12 — Admin alerts (v0)
- Added an admin-only Alerts feed:
  - Fresh BUY/AVOID appeared (Fresh Whale Signals diff vs previous run)
  - Trend flips (bull/bear) for curated ETF/dividend watchlists

## 2026-02-14 — Subscriber email (pilot)
- Pilot-stage email delivery uses **SMTP** (Gmail + App Password recommended).
- Subscription uses **double opt-in**: `/subscribe` sends a confirm link; `/confirm` activates.
- Every daily send creates an auditable artifact:
  - `alert_runs` (policy + source snapshot run ids)
  - `alert_items` (BUY/SELL only)
  - `alert_deliveries` (per-subscriber send status)

## 2026-02-14 — Subscriber thresholds (v0)
- Subscriber alert thresholds are configurable from the admin dashboard (Tools) and persisted in `admin_settings` under key `subscriber_alert_policy_v0`.
- Pilot emails are **plain-text only** for deliverability and speed.

## 2026-02-14 — Subscriber reliability (v0)
- Emails are **diff-gated** (if alert items didn’t change vs the previous run, deliveries are recorded as `skipped`).
- Admin dashboard includes a **deliveries history** view (last 5 days by default) to debug send outcomes without CLI.

## 2026-02-14 — Manual-only subscriber sending (v0)
- Alert **generation is automatic** (dashboard always has a “today” draft for admin review).
- Email **sending is manual** from the dashboard:
  - Per-item **Send** sends just that alert (creates a separate run for audit/history).
  - **Send All** sends the full draft run.
- Runs tab keeps the existing history UI; “Generate Draft Now” remains available for ad-hoc regeneration/testing.

## 2026-02-14 — Fresh Whale Signals avoid gating tweak
- `avoid` now requires **bearish trend**, or **net insider selling while trend is not bullish**.
- Rationale: if trend is strongly bullish (close>SMA50 and 20D>0), insider selling is treated as **risk/watch**, not an automatic avoid.

## 2026-02-14 — Admin authentication (pilot)
- Add a simple admin login flow (password-only) and protect all `/admin/*` endpoints when `WEALTHPULSE_ADMIN_PASSWORD` is set.
- Token transport: `Authorization: Bearer <token>` stored in browser local storage (pilot simplicity).

## 2026-02-15 — Cloud deploy (v0)
- Deployment target: single VM (AWS/GCP neutral) using Docker Compose with:
  - `web` (Caddy reverse proxy + static frontend)
  - `backend` (FastAPI/Uvicorn)
  - `db` (Postgres, containerized)
- Public ports: expose **80** only (IP-only pilot); backend port **8000** remains internal.
- Routing: `/api/*` is reverse-proxied to backend; `/subscribe`, `/confirm`, `/unsubscribe` are served by backend via proxy.
- Subscription links: `WEALTHPULSE_PUBLIC_BASE_URL` must point to the public origin (no `:8000`).

## 2026-02-15 — Insider quality filtering (v0.1 design)
- Add an “Insider Quality Filter” layer for Form 4 to reduce noise and improve explainability:
  - Transaction codes:
    - Treat **`P` (open market purchase)** as the primary bullish insider signal.
    - Treat **`S` (open market sale)** as bearish/risk (context-aware; do not force `avoid` if trend is strongly bullish).
    - Ignore common non-informative codes for scoring: **`A` (grant/award)**, **`M` (exercise/conversion)**, **`G` (gift)**.
  - If the Form 4 indicates a **10b5-1 plan trade**, downweight intent (scheduled) relative to discretionary trades.
  - Add **cluster buy** detection (≥3 distinct insiders with `P` within a short window) as a confidence booster.

## 2026-02-15 — Listener model + refresh lanes (v0.1 design)
- Adopt a “three listeners” operational model to keep the backend modular and the scoring explainable:
  - **Auditor:** SEC filings (Form 4 + SC 13D/13G) → normalized evidence + corroborators + quality filters.
  - **Mapmaker:** price-derived technicals (SMA50/SMA200, simple support/resistance) → guardrail multiplier/penalty.
  - **Listener (optional):** social cashtag velocity (Reddit/X) with persistence/cooldown to reduce noise.
- Refresh frequency becomes “lanes” (cost control):
  - Mapmaker: **15–60 min during market hours** (pilot default; not high-frequency).
  - Auditor: **10–30 min best-effort weekdays** with backoff to avoid EDGAR blocks.
  - Social Listener: **10–15 min** (optional; feature-flagged until sources are chosen).
  - Fundamentals/static: **daily**.
- Scheduling remains minimal: on-demand in dev; **cron** on the VM calling existing CLI commands in prod.

## 2026-02-15 — Mapmaker technical guardrails (v0.1 implementation)
- Expanded the trend payload to include a lightweight technical snapshot:
  - SMA50/SMA200, 20D/60D return, 60D high/low proximity, and derived distance-to-level fields.
- Added a “technical guardrail” layer that applies a small **Ft multiplier/penalty** to reduce chasing:
  - Boosts slightly when near SMA50 support in a bullish setup.
  - Penalizes when extended above SMA50 and/or near the 60D high.
  - Adds a small penalty when below SMA200 in non-bullish setups.
- Stored breakdown in `reasons.tech_guardrail` for explainability and surfaced it in the detail drawer.

## 2026-02-15 — Auditor insider quality filter (v0.1 implementation)
- Added Form 4 10b5-1 parsing from XML (`aff10b5One`) and persisted per-transaction metadata in `insider_tx_meta`.
- Fresh Signals scoring now distinguishes discretionary vs planned insider transactions:
  - `P/S` discretionary carries full signal weight.
  - 10b5-1 `P/S` is downweighted (reliability + score contribution reduced).
  - `A/M/G` remain non-signal for scoring (query/scoring path remains focused on `P/S`).
- Added cluster buy detection in Fresh Signals:
  - Rule: at least 3 distinct insiders with discretionary `P` in the fresh window.
  - Effect: confidence boost + small score bonus.
- Top Picks corroborator now excludes 10b5-1 planned buys from “fresh insider buy” gating.
- UI drawer now surfaces insider quality fields:
  - 10b5-1 buy/sell totals + counts
  - cluster-buy yes/no + insider count

## 2026-02-15 — Divergence/conflict weighting (v0.1 implementation)
- Added explicit divergence modeling in Fresh Signals between insider flow and technical trend:
  - `bullish_divergence`: insider bullish while trend bearish (small positive score, confidence penalty).
  - `bearish_divergence`: insider bearish while trend bullish (larger negative score, confidence penalty).
  - `sc13_trend_conflict`: SC13 present while trend bearish (negative score/confidence adjustment).
  - `alignment`: insider and trend agree (small score/confidence boost).
- Applied divergence adjustments directly into score and confidence; stored in `reasons.divergence` for explainability.
- Added conservative avoid escalation when bearish divergence is present near the avoid threshold.
- Admin drawer now includes a dedicated Divergence block (type, directions, score/confidence adjustments, note).

## 2026-02-15 — Social listener (v0.1 implementation, feature-flagged)
- Added feature flags/settings:
  - `WEALTHPULSE_SOCIAL_ENABLED` (default false)
  - `WEALTHPULSE_SOCIAL_VELOCITY_THRESHOLD` (default 1.5)
  - `WEALTHPULSE_SOCIAL_MIN_MENTIONS` (default 5)
- Added `social_signals` table and CLI ingestion path:
  - `python -m app.cli ingest-social-signals-csv --csv-file <path>`
  - source is CSV/manual for pilot; no external provider dependency in v0.1.
- Fresh Signals scorer now optionally consumes social evidence:
  - uses mention velocity vs 7-day baseline
  - requires 2-bucket persistence for stronger effect
  - applies small score/confidence adjustments and stores details in `reasons.social` + `reasons.social_adjustment`
- UI drawer shows Social listener block when social evidence is present.
- Added operator tooling for faster pilot validation:
  - sample generator script: `scripts/generate_social_sample_csv.sh` (writes `/tmp/wealthpulse_social_sample.csv` by default)
  - Runs tab “Social Coverage” card backed by `/admin/social/coverage` (enabled flag, latest bucket, 24h rows/tickers, top mentioned tickers)
- Added Reddit live-ingest adapter (first external social source):
  - CLI: `python -m app.cli ingest-social-reddit`
  - default subreddits: `wallstreetbets,stocks,investing,options`
  - default extraction is strict cashtag mode (`$TICKER`) to reduce false positives
  - stores buckets in `social_signals` with source label `reddit:<subreddit>`
  - designed so X/Twitter listener can plug into the same `social_signals` schema later

## 2026-02-15 — Segment eligibility + primary selection (v0.1 implementation)
- Reworked Themes segmentation to use **per-ticker eligibility strength** instead of static first-match bucket assignment.
- For each ticker, the system now computes eligible segment candidates (`insider`, `activist`, `institutional`, `momentum`, `risk`) from Fresh Signals + Top Picks evidence, then chooses one primary segment.
- Added conservative Risk override rule: Risk becomes primary only when bearish strength is materially higher than the best non-risk candidate.
- Maintains “one ticker, one segment” while improving bucket relevance and reducing misleading priority artifacts.
- Endpoint payload now includes `meta.selection=eligibility_strength_primary_segment` for traceability.

## 2026-02-15 — Daily snapshot artifact (versioned/auditable)
- Added persistent `daily_snapshot_artifacts` table to store reproducible daily outputs.
- Added CLI command:
  - `python -m app.cli snapshot-daily-artifact-v0 --as-of <ISO>`
  - builds canonical payload from latest `recommendations_v0`, `fresh_signals_v0`, and `segments_v0`.
- Artifact payload is canonical-hashed (`sha256`) to support dedupe/replay and future backtest baselines.
- Added admin read endpoint:
  - `GET /admin/artifacts/daily/latest` for quick inspection/export.

## 2026-02-15 — Basic backtest harness (v0)
- Added snapshot backtest engine for `recommendations_v0` and `fresh_signals_v0` against a baseline ticker (default `SPY`).
- Added CLI:
  - `python -m app.cli backtest-snapshots-v0 --start-as-of YYYY-MM-DD --end-as-of YYYY-MM-DD`
  - horizons default to `5,20` trading days; evaluates top buy/avoid rows per run.
- Metrics include:
  - evaluated coverage
  - average ticker return vs baseline return
  - average excess return
  - hit rate vs baseline (`buy`: ticker > baseline, `avoid`: ticker < baseline)
- Persists auditable backtest artifacts in `backtest_runs` and exposes latest via:
  - `GET /admin/backtests/latest`
- Admin Runs tab now includes a read-only Backtest card (coverage, hit-rate, excess return) sourced from latest backtest artifact.
