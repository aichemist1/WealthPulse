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
sudo docker compose --env-file prod.env exec -T backend python -m app.cli pipeline-status-v0 --lookback-days 7
```

This prints:
- ingestion/snapshot/artifact freshness summary
- latest alert draft status

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

### Backend fails with "Postgres is required ... points to SQLite"
Meaning: `WEALTHPULSE_DB_REQUIRE_POSTGRES=true` is enabled but `WEALTHPULSE_DB_URL` is still a SQLite URL.

Fix:
```bash
cd /opt/wealthpulse
grep -n WEALTHPULSE_DB_REQUIRE_POSTGRES prod.env
grep -n WEALTHPULSE_DB_URL prod.env
# Ensure DB URL is postgresql+psycopg://... and not sqlite://...
sudo docker compose --env-file prod.env up -d --build --force-recreate backend
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

### Top Picks / Dividend cards are missing
Run the integrated backend pipeline command:
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env exec -T backend python -m app.cli run-daily-pipeline-v0 --sec-lookback-days 3 --sec-limit 200 --top-n 20
```

If you are bootstrapping a brand-new environment with no 13F snapshot, run once with:
```bash
sudo docker compose --env-file prod.env exec -T backend python -m app.cli run-daily-pipeline-v0 --sec-lookback-days 3 --sec-limit 200 --top-n 20 --bootstrap-13f-if-missing
```

Then verify:
```bash
sudo docker compose --env-file prod.env exec -T backend python -m app.cli pipeline-status-v0 --lookback-days 7
```

## Smoke test
From the VM:
```bash
cd /opt/wealthpulse
WEALTHPULSE_BASE_URL="http://127.0.0.1" bash scripts/deploy_smoke_test.sh
```

## Ingestion + data validation runbook (reusable)

Use this when dashboard cards look empty or you need to prove what was ingested.

### 1) Rebuild backend and run pipeline once
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env up -d --build backend
sudo docker compose --env-file prod.env exec -T backend python -m app.cli run-daily-pipeline-v0 --sec-lookback-days 3 --sec-limit 200 --top-n 20 --no-run-backtest
```

### 2) Check pipeline + step telemetry from CLI
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env exec -T backend python -m app.cli pipeline-status-v0 --lookback-days 7
```

Expected: step lines for `form4`, `sc13`, `congress`, `prices`, `snapshots` with status and row counts.

### 3) Validate through backend API (Data Ops)
```bash
curl -s http://127.0.0.1:8000/admin/data-ops/latest
# or pretty-print:
curl -s http://127.0.0.1:8000/admin/data-ops/latest | jq
```

Check:
- `counts` (insider/sc13/congress/price/snapshots)
- `latest_events`
- `latest_pipeline_run.status`
- `latest_pipeline_run.steps[*]`

### 4) Query Postgres directly (ground truth)
```bash
cd /opt/wealthpulse
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select run_type,status,started_at,completed_at from ingestion_runs order by started_at desc limit 5;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select step_name,source_name,status,rows_ingested,latest_event_at,error_message from ingestion_step_runs order by started_at desc limit 20;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select count(*) as congress_rows from congress_trades;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select politician,ticker,trade_date,filing_date,amount_range from congress_trades order by coalesce(filing_date,trade_date) desc limit 10;"
```

### 5) Validate card source payloads
```bash
curl -s http://127.0.0.1:8000/admin/congress/latest | jq '.rows[:5]'
curl -s http://127.0.0.1:8000/admin/segments/latest | jq '.segments[] | {key,name,picks: (.picks|length)}'
```

## SQL validation queries (Postgres, DB-first)

Use these directly against Postgres to validate ingestion accuracy/relevance after each run.

### Latest pipeline run + step health
```bash
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select id,status,started_at,completed_at,summary_json from ingestion_runs order by started_at desc limit 1;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select step_name,source_name,status,rows_ingested,attempt_count,latest_event_at,error_message from ingestion_step_runs where ingestion_run_id=(select id from ingestion_runs order by started_at desc limit 1) order by started_at;"
```

### Source freshness + volume
```bash
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select 'form4' as src, count(*) rows, max(event_date) latest from insider_txs union all select 'sc13', count(*), max(filed_at) from large_owner_filings union all select 'congress', count(*), max(coalesce(filing_date, trade_date)) from congress_trades union all select 'prices', count(*), max(date::date) from price_bars;"
```

### Form 4 accuracy checks
```bash
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select count(*) total, count(*) filter (where ticker is null or ticker='') missing_ticker, count(*) filter (where transaction_code is null or transaction_code='') missing_code, count(*) filter (where event_date is null) missing_event_date from insider_txs;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select transaction_code, count(*) from insider_txs group by transaction_code order by count(*) desc;"
```

### SC13 accuracy checks
```bash
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select count(*) total, count(*) filter (where ticker is null or ticker='') missing_ticker, count(*) filter (where filed_at is null) missing_filed_at from large_owner_filings;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select form_type, count(*) from large_owner_filings group by form_type order by count(*) desc;"
```

### Congressional data checks
```bash
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select count(*) total, count(*) filter (where ticker is null or ticker='') missing_ticker, count(*) filter (where politician is null or politician='') missing_politician, count(*) filter (where coalesce(filing_date, trade_date) is null) missing_dates from congress_trades;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select source, count(*) from congress_trades group by source order by count(*) desc;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select politician,ticker,tx_type,amount_range,trade_date,filing_date,detected_at from congress_trades order by coalesce(filing_date,trade_date,detected_at) desc limit 30;"
```

### Snapshot usefulness checks
```bash
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select kind,as_of,id from snapshot_runs where kind in ('fresh_signals_v0','recommendations_v0') order by as_of desc limit 4;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select run_id,action,count(*) from snapshot_recommendations where run_id in (select id from snapshot_runs where kind in ('fresh_signals_v0','recommendations_v0') order by as_of desc limit 2) group by run_id,action order by run_id,action;"
sudo docker compose --env-file prod.env exec -T db psql -U wealthpulse -d wealthpulse -c "select ticker,action,score,confidence,segment from snapshot_recommendations where run_id=(select id from snapshot_runs where kind='fresh_signals_v0' order by as_of desc limit 1) order by score desc limit 25;"
```
