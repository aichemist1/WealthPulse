# WealthPulse — Functional Guide (v0)

This document explains what the dashboard does, what each number means, and how to interpret the outputs.

## What the product does
WealthPulse surfaces **actionable trading ideas** by combining:
- **Whale/institutional positioning** (13F deltas; delayed context)
- **Fresher corroborators** (trend, SC 13D/13G, insider buys)

The admin dashboard is designed to answer:
1) *What are the best ideas to look at today?* (Top Picks)
2) *Why is this idea here?* (Evidence + score breakdown)
3) *Is this “buy now” or just “watch”?* (Action gating + freshness)

## Core concepts

### 13F is context, not timing
13F filings reflect holdings **as of a quarter-end** (e.g., 2025-09-30) and are typically filed weeks later.
In v0, 13F is used to infer **conviction/accumulation**, not “they bought today”.

### Corroborators are timing
Corroborators are fresher signals that can support a “buy now” decision.
In v0 we use:
- **Trend** (daily prices): close vs SMA50 + 20D return
- **SC 13D/13G**: large-owner/activist filings (event-driven)
- **Form 4**: insider purchases (event-driven; can be sparse)

## Dashboard outputs

### Fresh Whale Signals (v0)
This card answers: **“What big-money events happened recently?”**

It’s built to be more *timely* than 13F and is driven by:
- **SC 13D/13G** filings (large-owner / activist events)
- **Form 4** insider buys/sells above a minimum value
- **Trend** (close vs SMA50 + 20D return)
- **Volume spike** (latest volume vs 20D avg; confirmation)

13F (if available) is shown as **context only** in the detail drawer.

### Avoid / Risk (v0)
This card is a conservative “things to be careful with” list derived from Fresh Whale Signals where `action=avoid`.
It is primarily driven by:
- meaningful insider selling and/or negative net insider flow (Form 4), and
- bearish recent trend confirmation.

It is **not** a short recommendation; treat it as a watchlist for risk management and further research.

### Dividend watchlist (v0)
The High-Yield Dividend Stocks card shows:
- price trend metrics (same as ETFs), and
- best-effort dividend fundamentals (Yahoo Finance): **TTM yield**, **payout ratio**, **ex-div date**.

These fundamentals are informational and may be stale or inaccurate for some tickers.

### Alerts (admin-only, v0)
The Alerts card surfaces:
- **Fresh BUY/AVOID appeared** (new tickers compared to the previous Fresh Whale Signals snapshot)
- **Trend flips** for your curated watchlists (ETF + dividends): bull/bear changes based on `close vs SMA50` and `20D return`

Alerts are meant to reduce “manual scanning” and help you focus on what changed since the prior run.

### Top Picks (v0)
Each row is a ticker with:
- **Score (0–100)**: combined whale + timing score
- **Action**: `watch` or `buy` (v0)
- **Confidence (0–1)**: “how reliable is this signal under our data coverage + sample size + corroborators”, not a probability of profit
- **Why**: short reason string + key numeric evidence

Click a ticker to open the **detail drawer**.

### Detail drawer
Shows:
- **Evidence (13F):** report period, previous period, QoQ delta value, total value, breadth
- **Trend metrics:** last close, SMA50, 20D return, last price date
- **Score breakdown:** magnitude/breadth/size/penalties + whale score + trend adjustment
- **Corroborators:** which are present in the freshness window
- **Action rule (v0):** why it’s `watch` vs `buy`

## How scoring works (v0)

### Whale score (context)
Derived from the latest stored 13F delta snapshot:
- **Magnitude (rank-based):** larger QoQ delta ranks higher (cross-sectional rank vs the current ingested universe)
- **Breadth:** `manager_increase_count / manager_count`
- **Size:** log-scaled `total_value_usd`
- **Penalties:**
  - low CUSIP→ticker mapping coverage
  - small sample size (few managers in our ingested set)

The drawer shows these as `score_breakdown.*`.

Implementation note (v0 weights):
- Magnitude: up to **55** points
- Breadth: up to **25** points
- Size: up to **10** points
- Penalties: up to **-20** points (coverage + sample-size)

### Trend adjustment (timing)
If trend data exists:
- bullish trend: **+8**
- not bullish: **-8**

The final Score is:
- `score = clamp(whale_score + trend_adjustment, 0, 100)`

This is why two names with similar whale score can diverge if one has a better setup.

## What Confidence means (v0)
Confidence is capped because 13F is delayed and our universe/coverage may be incomplete.
It increases with:
- higher whale magnitude
- larger/broader manager participation
- bullish trend corroboration

It decreases with:
- poor CUSIP→ticker coverage
- tiny manager counts (sample risk)
- bearish/no trend signal (timing risk)

Confidence is **not** “chance it goes up”; it’s **signal reliability** under current data quality.

Implementation note (v0):
- Confidence starts at **0.20** and is increased by manager breadth and delta magnitude (relative to current universe).
- It is reduced when CUSIP→ticker mapping coverage is low.
- It is clamped to **[0.05, 0.65]** for the 13F-only base score.
- Then the recommendations job may adjust confidence:
  - Trend bullish recent: **+0.10** (capped)
  - Trend not bullish (but trend data exists): **-0.05** (floored)
  - Action upgraded to BUY: additional **+0.20** (capped)

## Action rules (v0)
Default is `watch` because 13F is delayed.

It becomes `buy` only if:
- `score >= buy_score_threshold` AND
- at least one **fresh corroborator** exists:
  - SC 13D/13G recent, OR
  - insider buy recent ≥ `insider_min_value`, OR
  - bullish trend recent

### Fresh Whale Signals action rules (v0)
Fresh Whale Signals uses `buy`, `watch`, and `avoid`:
- **BUY**: score ≥ threshold **and** (fresh SC13 or insider net buy) **and** bullish trend or positive net insider flow
- **AVOID**: score ≤ threshold **and** (fresh insider net sell) **and** bearish trend or negative net insider flow
- **WATCH**: everything else (keep it conservative; corroborate with your own research)

Implementation note (v0):
- Fresh Whale Signals score is centered at **50 = neutral** (above 50 = more bullish, below 50 = more bearish).

## Practical interpretation (how to use it)
- Treat **Watch** as “shortlist for research + set alerts”.
- Treat **Buy** as “setup aligns with whale context + a fresh corroborator exists”; still apply your own risk rules.
- Always read the drawer’s evidence dates to avoid acting on stale context.

## FAQ (answers to common “why?” questions)

### “Why is `Trend bullish (recent)` = no even when the price went up?”
Because v0 defines bullish trend as **both**:
- `close > SMA50`, and
- `20D return > 0`

So a name can be up on a short window and still show `no` if it’s below the 50-day average (or if our latest bar is stale relative to `as_of`).

Also: “recent” trend is intentionally short-horizon. A stock can be up over ~3 months and still have a negative 20D return (or dip below SMA50), which will flip `bullish_recent` to `no`. Use the drawer’s 60D return (when present) for a longer lens.

### “Is `Trend bullish (recent)` tied to SC 13D/13G?”
No. They are separate corroborators:
- Trend is computed from **price bars**
- SC 13D/13G is computed from **SEC filings**

You can have trend = yes and SC13 = no (and vice versa).

### “How often are SC 13D/13G filings reported?”
They are **event-driven**, not periodic:
- A 13D/13G appears when someone crosses reporting thresholds or materially changes a stake.
- Amendments are filed when ownership changes or disclosures change.

So for many large caps, you can go long stretches with no SC 13D/13G activity.

### “Why don’t Score / Confidence match the last 20D return?”
Because v0 Score/Confidence are **not** “expected return” metrics.

- Score is a **ranked, explainable signal strength** measure (whale context + timing corroboration).
- Confidence is a **data/signal reliability** measure (coverage + sample size + corroborators).
- 20D return is displayed as part of the **trend corroborator**, not as a training target.

It’s normal for a strong recent return to still be `watch` if the whale context is weak or corroborators are missing, and vice versa.

## Current limitations (expected for v0)
- 13F coverage depends on which filing days/managers you ingest (sampling effects).
- Mapping coverage (CUSIP→ticker) may be incomplete (OpenFIGI limits).
- Trend uses a free source (Stooq) and may lag/skip some symbols.
- No news/catalyst scoring yet.
- No backtest metrics in the UI yet.
