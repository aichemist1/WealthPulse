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

## Code (in progress)
- Backend (FastAPI/SQLite): `backend/`
- Frontend (admin UI): `frontend/`
