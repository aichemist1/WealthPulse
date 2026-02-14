# WealthPulse — Roadmap & Progress

This file is the checklist to track phases and to pause/resume cleanly.

## Phase 0 — Product lock (Blueprint)
- [ ] Finalize segment list (names + descriptions shown on dashboard)
- [x] Lock “one stock, one segment” behavior
- [x] Lock segment priority + stability rule
- [x] Lock access model (admin dashboard; subscribers alerts only)
- [x] Lock alert payload (Buy/Sell only; max 5/day)
- [x] Lock daily schedule (weekdays 8:30 AM CST)
- [x] Choose initial delivery channel (email only)
- [x] Lock v0 stack (React/FastAPI/SQLite)

## Phase 1 — Data foundation (Ingestion + schemas)
- [x] Define canonical schemas (Stock, Filing, Event, Investor, InsiderTx)
- [x] Ingest Tier A sources (Form 4, 13D/13G) (v0: header-level SC13 parsing; Form 4 transaction parsing)
- [x] Add idempotency + dedupe keys + replay capability (basic unique keys + raw payload store)
- [ ] Data quality checks (staleness, missing fields, parsing failures) (partial: coverage + run metrics exist)
- [ ] Dashboard data warnings (show stale/partial feeds)

### Notes (as of 2026-02-11)
- Backend scaffolding exists in `backend/` with local dev-only Form 4 XML ingestion.
- Live SEC EDGAR Form 4 ingestion command exists (`python -m app.cli ingest-form4-edgar`) and is wired into the demo script (best-effort).
- Live SEC EDGAR 13F ingestion command exists (`python -m app.cli ingest-13f-edgar`) and a 13F delta snapshot exists (`python -m app.cli snapshot-13f-whales`) (CUSIP-based); tested end-to-end against SEC on 2025-11-14.
- Live SEC EDGAR 13D/13G ingestion exists (`python -m app.cli ingest-sc13-edgar`) and is used as a corroborator (v0 parses header-level metadata and maps issuer CIK → ticker).

## Phase 2 — Signals & scoring (Explainable)
- [x] Implement initial signals (13F accumulation snapshot + deltas; basic insider whale snapshot)
- [x] Implement scoring + confidence (v0 13F-based Top Picks; Watch/Buy with corroborator gating + trend adjustment)
- [x] Implement Fresh Whale Signals (SC13 + Form4 + trend/volume) snapshot (v0)
- [ ] Implement segment eligibility + primary segment selection
- [ ] Produce daily snapshot artifact (versioned, auditable)
- [ ] Basic backtest harness (5D/20D) + baseline comparison

## Phase 3 — Admin dashboard (Private)
- [x] Dashboard: segments row (Themes)
- [ ] Dashboard: top movers
- [x] Dashboard: top picks + insider feed (+ drill-down drawer)
- [x] Dashboard: ETF / Macro Plays card (seed: GLD, AIQ, QTUM, SKYY, MAGS, JTEK, ARKW, CHAT, HACK)
- [x] Dashboard: High-Yield Dividend Stocks card (seed: VNOM, SLB, EOG; integrate dividend yield data later)
- [x] Dividend fundamentals (v0): show yield, payout ratio, ex-div date for dividend watchlist
- [x] Stock detail drawer: evidence timeline + score breakdown (v0 for Top Picks)
- [ ] Admin tools: thresholds, allow/deny lists, segment priority config
- [x] Admin QA view: snapshot health + run browser + coverage (moved to Runs tab)
- [x] Admin-only Alerts feed (backend implemented; UI currently focused on subscriber alert review)
- [x] Subscriber Alerts (manual send) card on Latest (auto-drafted daily; per-item send + send-all)
- [ ] Admin authentication (login) + basic access control (before cloud deploy)

## Phase 4 — Subscriber alerts (Subscription)
- [x] Subscription schema + double opt-in (confirm + unsubscribe tokens)
- [x] Deliver email alerts (pilot SMTP; Gmail app password recommended)
- [x] Daily alert artifact (AlertRun + AlertItems + deliveries log)
- [x] Admin thresholds for subscriber alerts (Tools panel + persisted settings)
- [x] Diff-based sending (skip if no changes)
- [x] Deliveries history (admin UI, last 5 days)
- [x] Manual-only send (admin review; sending is explicit)
- [x] Auto-generate daily draft for admin review (no auto-send)
- [ ] Subscription tiers + limits (daily alerts, #stocks, segments)
- [ ] Alert generation schedule control (time-of-day draft build; timezone config)
- [ ] Compliance copy/disclosures + audit trail per alert (partial: basic disclaimer + run artifacts exist)

## Phase 5 — Reliability & scale
- [ ] Observability dashboards + alerting on pipeline failures
- [ ] Backtesting harness + evaluation metrics
- [ ] Vendor hardening (rate limits, retries, DLQ)
- [ ] Performance tuning (caching, precompute, pagination)
