# WealthPulse — Deployment Guide (v0)

Goal: **cloud-agnostic**, **containerized**, **minimum cost**, and **incremental hardening**.

This guide assumes:
- Subscribers are **email-only** (no dashboard access).
- Admin uses the dashboard (protected by `WEALTHPULSE_ADMIN_PASSWORD` in pilot).
- Initial deploy uses a **VM public IP** (domain/TLS can come later).
- Database is **Postgres** (as requested).

## v0 architecture (minimum moving parts)
Run everything on **one VM** with **Docker Compose**:
- `web`: reverse proxy + serves the built frontend (static assets)
- `backend`: FastAPI/Uvicorn API + CLI jobs (ingestion/snapshots/email)
- `db`: Postgres

Data persistence:
- Postgres stores all application state (subscriptions, alert runs, deliveries, snapshots).
- Postgres data directory is mounted to a persistent volume/disk.

What we *avoid* in v0:
- Kubernetes
- Redis/queues
- Managed DB (RDS/Cloud SQL)
- “Migration framework work” (Alembic) — we can add later when schema churn increases

## VM prerequisites (AWS/GCP-neutral)
- A small Linux VM (start small; resize later if needed).
- Install Docker + Docker Compose plugin.
- Firewall rules:
  - Allow inbound `80/tcp` (required for IP-only pilot).
  - Allow inbound `443/tcp` (recommended later when you add a domain + TLS).
  - **Do not expose Postgres `5432` publicly.**

## Required configuration (env vars)
Create a `prod.env` file on the VM (do not commit).

### Database (Postgres)
- `POSTGRES_DB=wealthpulse`
- `POSTGRES_USER=wealthpulse`
- `POSTGRES_PASSWORD=...`

Backend DB URL (container-to-container hostname `db`):
- `WEALTHPULSE_DB_URL=postgresql+psycopg://wealthpulse:<POSTGRES_PASSWORD>@db:5432/wealthpulse`

### Public base URL (important for email links)
For IP-only pilot:
- `WEALTHPULSE_PUBLIC_BASE_URL=http://<VM_PUBLIC_IP>`

This controls the links in:
- confirmation email (`/confirm?token=...`)
- unsubscribe link (`/unsubscribe?token=...`)
- public subscribe page (`/subscribe`)

### Admin auth (recommended even for pilot)
- `WEALTHPULSE_ADMIN_PASSWORD=...` (enable admin protection for all `/admin/*`)
- `WEALTHPULSE_ADMIN_TOKEN_SECRET=...` (recommended: independent signing secret)

### CORS (admin UI)
- `WEALTHPULSE_CORS_ORIGINS=http://<VM_PUBLIC_IP>` (or your domain later)

### SEC EDGAR access
- `WEALTHPULSE_SEC_USER_AGENT=WealthPulse (you@domain.com)`

### SMTP (email)
- `WEALTHPULSE_SMTP_HOST=...`
- `WEALTHPULSE_SMTP_PORT=587`
- `WEALTHPULSE_SMTP_USE_STARTTLS=true`
- `WEALTHPULSE_SMTP_USER=...`
- `WEALTHPULSE_SMTP_PASSWORD=...`
- `WEALTHPULSE_SMTP_FROM_EMAIL=...`
- `WEALTHPULSE_SMTP_FROM_NAME=WealthPulse`

## v0 Docker Compose spec (recommended)
Decision set: **1A + 2A + 3A**:
- only `web` is public (`:80`)
- Postgres runs on the same VM via Compose
- cron on the VM calls backend CLI inside the container

### Service responsibilities
- `web`:
  - serves the built admin UI (static)
  - proxies API calls: `/api/*` → `backend`
- `backend`:
  - FastAPI/Uvicorn app
  - ingestion + snapshot CLI commands run in this container
- `db`:
  - Postgres
  - data stored on a persistent volume

### Compose file outline
We provide these files at repo root:
- `docker-compose.yml`
- `Dockerfile.backend`
- `Dockerfile.web`
- `Caddyfile`
- `prod.env.example` (copy to `prod.env` on the VM)

Compose shape:
- `web` publishes `80:80`
- `backend` listens on `8000` **internally only**
- `db` listens on `5432` **internally only** (not published)
- `db` uses a named volume: `wealthpulse_pgdata`

### URL routing
To keep the backend private, the reverse proxy handles:
- `http://<VM_IP>/` → admin UI
- `http://<VM_IP>/api/*` → backend (proxy to `http://backend:8000/*`)

Important: this implies the frontend is built with:
- `VITE_API_BASE_URL=/api`

## prod.env template (VM)
Create a file like `/opt/wealthpulse/prod.env` (example path) and keep permissions tight.

```bash
# --- Postgres container ---
POSTGRES_DB=wealthpulse
POSTGRES_USER=wealthpulse
POSTGRES_PASSWORD=change_me

# --- WealthPulse backend ---
WEALTHPULSE_DB_URL=postgresql+psycopg://wealthpulse:change_me@db:5432/wealthpulse
WEALTHPULSE_PUBLIC_BASE_URL=http://<VM_PUBLIC_IP>
WEALTHPULSE_CORS_ORIGINS=http://<VM_PUBLIC_IP>
WEALTHPULSE_SEC_USER_AGENT=WealthPulse (you@domain.com)

# Admin auth (enable in prod)
WEALTHPULSE_ADMIN_PASSWORD=change_me
WEALTHPULSE_ADMIN_TOKEN_SECRET=change_me_too

# SMTP (email)
WEALTHPULSE_SMTP_HOST=smtp.gmail.com
WEALTHPULSE_SMTP_PORT=587
WEALTHPULSE_SMTP_USE_STARTTLS=true
WEALTHPULSE_SMTP_USER=your@gmail.com
WEALTHPULSE_SMTP_PASSWORD=your_app_password
WEALTHPULSE_SMTP_FROM_EMAIL=your@gmail.com
WEALTHPULSE_SMTP_FROM_NAME=WealthPulse
```

## Deploy on a VM (IP-only pilot)
On the VM:

1) Copy env template and edit:
```bash
cp prod.env.example prod.env
chmod 600 prod.env
```

2) Build + start:
```bash
docker compose --env-file prod.env up -d --build
```

3) Smoke test (from the VM):
```bash
WEALTHPULSE_BASE_URL="http://127.0.0.1" bash scripts/deploy_smoke_test.sh
```

From your laptop, open:
- `http://<VM_PUBLIC_IP>/` (admin UI)
- `http://<VM_PUBLIC_IP>/subscribe` (public subscribe page)

## One-click cloud-agnostic deploy (recommended)
If you don’t want Docker locally, use the SSH deploy helper (runs everything on the VM):

1) Create a VM (AWS/GCP) and ensure inbound port `80` is open.
2) Copy env template for the deploy script:
```bash
cp scripts/cloud_deploy.env.example scripts/cloud_deploy.env
chmod 600 scripts/cloud_deploy.env
```
3) Create your production env:
```bash
cp prod.env.example prod.env
chmod 600 prod.env
```
4) Run the deploy:
```bash
bash scripts/cloud_deploy_vm.sh
```

This script:
- installs Docker on the VM (Ubuntu) if missing
- uploads the repo
- uploads `prod.env`
- runs `docker compose up -d --build`
- runs a smoke test from the VM

## AWS deploy without SSH (SSM)
If you don’t want inbound SSH at all, use AWS Systems Manager (SSM) Run Command.

Prereqs:
- Instance is managed by SSM (agent + IAM role `AmazonSSMManagedInstanceCore`)
- Outbound access to SSM endpoints
- Your local machine has `aws` CLI configured (you already set `AWS_PROFILE=...`)

Steps:
1) `cp scripts/aws_deploy_ssm.env.example scripts/aws_deploy_ssm.env`
2) Fill:
   - `AWS_PROFILE`, `AWS_REGION`
   - `WEALTHPULSE_AWS_INSTANCE_ID`
   - `WEALTHPULSE_REPO_URL` (repo must contain the code you want to deploy)
3) `cp prod.env.example prod.env` (fill values; set `WEALTHPULSE_PUBLIC_BASE_URL` to the EC2 public IP)
4) Run:
```bash
bash scripts/aws_deploy_ssm.sh
```

Note: v0 script uploads `prod.env` content via SSM command payload (base64). For stronger secrecy later, move secrets to Parameter Store / Secrets Manager.

## Cron spec (VM) — v0
Run jobs from the VM (cheapest) by executing the backend CLI inside the container.

Recommended cadence (pilot):
- **Daily**: refresh data (best-effort), compute snapshots, generate the subscriber alert draft
- **Manual**: admin reviews and clicks Send in the dashboard (no auto-send)

Example cron outline (exact commands finalized once Compose service names are fixed):
- `docker compose exec -T backend python -m app.cli ingest-form4-edgar --day YYYY-MM-DD --limit N`
- `docker compose exec -T backend python -m app.cli ingest-sc13-edgar --day YYYY-MM-DD --limit N`
- `docker compose exec -T backend python -m app.cli snapshot-recommendations-v0 ...`
- `docker compose exec -T backend python -m app.cli snapshot-fresh-signals-v0 ...`
- `docker compose exec -T backend python -m app.cli send-daily-subscriber-alerts-v0` (draft-only by default)

## Smoke-test checklist (per deploy)
After `docker compose up -d`:
- `GET /health` returns `{"status":"ok"}`
- Admin UI loads at `http://<VM_IP>/`
- Login works (if admin auth enabled)
- `http://<VM_IP>/subscribe` page loads and can submit an email
- Confirmation link uses the correct base URL (`WEALTHPULSE_PUBLIC_BASE_URL`)
- Subscriber tab shows DB rows (Postgres persistence)

For common issues and quick restart commands, see `TROUBLESHOOTING.md`.

## Deployment path (integrate changes without breaking)
Keep deployments repeatable:
1) Update code (or pull updated images)
2) Restart the Compose stack
3) Run smoke checks

Suggested minimal smoke checks:
- `GET /health` returns `{"status":"ok"}`
- Open admin UI, login works
- `GET /subscribe` page loads
- Confirm/unsubscribe links resolve (base URL correct)
- Test email send to yourself

## Running jobs (pilot)
Cheapest approach: VM cron triggers backend CLI commands (inside the container).
Examples (conceptual):
- Daily ingestion (optional / best-effort)
- Daily snapshot generation
- Daily draft generation (subscriber alerts for admin review)

Keep it simple until value is validated.

## Security path (incremental)
v0 baseline:
- Enable admin auth (`WEALTHPULSE_ADMIN_PASSWORD`)
- Only expose ports 80/443
- Do not expose Postgres publicly
- Use strong secrets in `prod.env`

Later hardening (after pilot proves value):
- Domain + TLS
- Proper admin identity (OAuth or hashed password + session cookies)
- Reverse-proxy rate limits for `/admin/auth/login` and `/subscribe`
- Automated backups off-VM (S3/GCS)
