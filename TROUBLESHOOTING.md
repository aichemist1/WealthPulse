# WealthPulse — Troubleshooting (v0)

This page captures common pilot deployment issues and the exact commands to recover quickly.

Applies to the Docker Compose deployment described in `DEPLOYMENT.md` (VM IP-based, `web` + `backend` + `db`).

Assumptions:
- You deployed to `/opt/wealthpulse` on the VM/EC2.
- You have a `prod.env` file in that directory.

## Quick restart commands (EC2/VM)

### Restart everything
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env down
sudo docker compose --env-file prod.env up -d
```

### Rebuild + recreate everything
Use this after pulling new code or changing Dockerfiles.
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env up -d --build --force-recreate
```

### Recreate only backend
Use this after changing backend code or backend-related env vars (SMTP, DB URL, PUBLIC_BASE_URL, admin auth).
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env up -d --build --force-recreate backend
```

## Daily pipeline (manual rerun + cron)

### Run the full daily pipeline now
```bash
cd /opt/wealthpulse
bash scripts/pipeline_daily_compose.sh
```

### Check pipeline logs
```bash
sudo tail -n 200 /var/log/wealthpulse/daily_pipeline.log
```

### Check/install cron entry
```bash
crontab -l | grep wealthpulse-daily-pipeline || true
cd /opt/wealthpulse
bash scripts/install_daily_pipeline_cron.sh
crontab -l
```

### One-command status verification (recommended)
```bash
cd /opt/wealthpulse
bash scripts/pipeline_status_compose.sh
```

This prints:
- container status
- ingestion/snapshot/artifact freshness summary
- tail of `daily_pipeline.log`

### Recreate only web (Caddy + frontend)
Use this after changing `Caddyfile` or frontend build behavior.
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env up -d --build --force-recreate web
```

## Logs and status

### Container status
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env ps
```

### Tail logs
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env logs -n 200 --no-color web
sudo docker compose --env-file prod.env logs -n 200 --no-color backend
sudo docker compose --env-file prod.env logs -n 200 --no-color db
```

## Common issues

### UI shows: `SyntaxError: Unexpected token '<' ... is not valid JSON`
Meaning: the UI requested JSON but received HTML (usually `index.html`). In our setup this typically happens when:
- `/api/*` is not being proxied to the backend, OR
- the frontend is using the wrong API base URL.

Checks (run on the VM):
```bash
curl -i http://127.0.0.1/api/admin/auth/status
```
Expected:
- `200` with JSON, OR
- `401` with JSON (if admin auth enabled and you are not logged in).

If you see HTML instead, rebuild/recreate `web`:
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env up -d --build --force-recreate web
```

### `/subscribe` returns `Internal Server Error`
Meaning: backend exception rendering the subscribe page.

Action:
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env logs -n 200 --no-color backend
sudo docker compose --env-file prod.env up -d --build --force-recreate backend
```

### Subscription confirm link points to `:8000` (or `localhost`)
Meaning: `WEALTHPULSE_PUBLIC_BASE_URL` is incorrect. Confirm/unsubscribe links must be reachable from the user.

Fix on the VM:
```bash
cd /opt/wealthpulse
grep -n WEALTHPULSE_PUBLIC_BASE_URL prod.env
# Set to:
# WEALTHPULSE_PUBLIC_BASE_URL=http://<VM_PUBLIC_IP>

sudo docker compose --env-file prod.env up -d --force-recreate backend
```

Notes:
- In this deployment, **port 80** is public. Backend port 8000 is **not** exposed.
- Old emails keep old links; re-invite or manually replace the URL.

### Compose warning: `WEALTHPULSE_DB_URL variable is not set`
Meaning: you ran docker compose without `--env-file prod.env`, or `prod.env` is missing the variable.

Fix:
```bash
cd /opt/wealthpulse
grep -n WEALTHPULSE_DB_URL prod.env || echo "MISSING"
sudo docker compose --env-file prod.env up -d --force-recreate backend
```

### UI loads but no data appears
Meaning: the DB likely has no ingested data/snapshots yet (fresh Postgres volume).

Run minimal ingestion + snapshots (pick a day you care about):
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env exec backend python -m app.cli init-db

sudo docker compose --env-file prod.env exec backend python -m app.cli ingest-form4-edgar --day 2025-11-14 --limit 50
sudo docker compose --env-file prod.env exec backend python -m app.cli ingest-sc13-edgar --day 2025-11-14 --limit 50

sudo docker compose --env-file prod.env exec backend python -m app.cli snapshot-fresh-signals-v0 --as-of 2025-11-15 --fresh-days 30 --insider-min-value 10000 --top-n 20
sudo docker compose --env-file prod.env exec backend python -m app.cli snapshot-recommendations-v0 --as-of 2025-11-15 --fresh-days 7 --buy-score-threshold 70 --insider-min-value 100000 --top-n 20
```

## Smoke test
From the VM:
```bash
cd /opt/wealthpulse
WEALTHPULSE_BASE_URL="http://127.0.0.1" bash scripts/deploy_smoke_test.sh
```
