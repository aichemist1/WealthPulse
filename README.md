# WealthPulse

Admin-only intelligent trading advisor dashboard + subscriber notifications (Buy/Sell/Watch).

## What this is
- **Admin dashboard (private):** segments/themes, top picks, movers, insider activity, and drill-down explanations.
- **Subscribers (no dashboard access):** receive daily alerts with actionable recommendations and short explanations.

## Key product decisions (current)
- **One stock shown in one segment** (no duplication), chosen by **fixed priority + score tiebreaker**, with a stability rule.
- Signals start with **13D/13G**, **Form 4**, and **13F**; block-trade detection can be added later via vendor data.

## Docs
- Design: `DESIGN.md`
- Functional guide (what the UI means): `FUNCTIONAL.md`
- Roadmap/progress: `ROADMAP.md`
- Decisions log (pause/resume context): `DECISIONS.md`
- Deployment guide (cloud-agnostic v0): `DEPLOYMENT.md`
- Troubleshooting (common fixes/commands): `TROUBLESHOOTING.md`

## Quick demo (local)
```bash
export WEALTHPULSE_SEC_USER_AGENT='WealthPulse (you@domain.com)'
./run_demo_dashboard.sh
```

## Pilot subscriptions (email)
We use SMTP for pilot stage (Gmail + App Password recommended).

Quick pilot helper (avoids retyping env vars):
```bash
cp scripts/pilot.env.example scripts/pilot.env
chmod 600 scripts/pilot.env
bash scripts/pilot.sh dashboard
```

Required env (example for Gmail):
```bash
export WEALTHPULSE_SMTP_HOST='smtp.gmail.com'
export WEALTHPULSE_SMTP_PORT='587'
export WEALTHPULSE_SMTP_USE_STARTTLS='true'
export WEALTHPULSE_SMTP_USER='your@gmail.com'
export WEALTHPULSE_SMTP_PASSWORD='your_app_password'
export WEALTHPULSE_SMTP_FROM_EMAIL='your@gmail.com'
export WEALTHPULSE_PUBLIC_BASE_URL='http://localhost:8000'
```

Create a subscriber (sends confirm link):
```bash
cd backend
python -m app.cli subscribe-email --email 'you@domain.com'
```

Send daily subscriber alerts (to all active subscribers):
```bash
cd backend
python -m app.cli send-daily-subscriber-alerts-v0
```

## Code (in progress)
- Backend (FastAPI/SQLite): `backend/`
- Frontend (admin UI): `frontend/`

## Data Provider Reference (Cost Strategy)

### 1) The "Free" Data Stack ($0 Cost)
| Source | Free Tier Details | Best Use Case |
|---|---|---|
| CapitolTrades.com | 100% Free. No registration needed. | Political Trades: Use this for manual verification or lightweight scraping of Congressional trades (like your `$PLD` example). |
| SEC EDGAR API | 100% Free. Government-run. | Insiders (Form 4): Raw source for every CEO/Director buy. Most accurate but requires technical parsing. |
| OpenInsider | Free Web Access. | Insider Filtering: Quick way to find "Cluster Buys" and "Open Market Purchases" (Code `P`) without a subscription. |
| Finnhub.io | Free Tier available. | Social Sentiment: Provides basic sentiment analysis and stock news for free with rate limits. |
| Financial Modeling Prep (FMP) | 250 calls/day free. | All-in-One: Great for pulling basic stock quotes and Senate/House disclosures for testing. |
| Alpaca Markets | Free API Key. | Real-Time Price: Provides real-time trade data (IEX exchange only) at no cost. |

### 2) The "Freemium" Transition (Starts Free, Then Paid)
These sources are useful early, but likely require paid plans as automation/usage scales.

- **Quiver Quantitative**
  - Free: Basic web access to see which politicians are trading what.
  - Paid (`$25/mo`): API access for automated dashboard ingestion.

- **WhaleWisdom**
  - Free: View last 2 years of 13F (institutional) data and set up 5 email alerts.
  - Paid (`$90/qtr`): API access to download data into your own database.

- **Unusual Whales**
  - Free: Limited "Shamu" highlights on website.
  - Paid (`$50/mo`): Options flow (whale trades), one of the hardest datasets to source for free in real-time.

### 3) Factual Recommendation for This Dashboard
To keep costs near `$0` during build/pilot:

- **Political/Whale Data:** Use CapitolTrades.com and OpenInsider as web views (manual/embedded visibility) before API spend.
- **Market/Fundamentals:** Use FMP free tier (`250 calls/day`) for a 10–20 stock watchlist refreshed a few times daily.
- **Real-Time Alerts:** Use Alpaca for price feed (free, factual, institutional-grade for pilot use).
