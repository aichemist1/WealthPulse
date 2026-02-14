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
