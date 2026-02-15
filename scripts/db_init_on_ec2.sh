cd /opt/wealthpulse

# Initialize tables (safe to re-run)
sudo docker compose --env-file prod.env exec backend python -m app.cli init-db

# Ingest a small sample (pick a recent day you want)
sudo docker compose --env-file prod.env exec backend python -m app.cli ingest-form4-edgar --day 2025-11-14 --limit 50
sudo docker compose --env-file prod.env exec backend python -m app.cli ingest-sc13-edgar --day 2025-11-14 --limit 50

# Compute snapshots (as-of)
sudo docker compose --env-file prod.env exec backend python -m app.cli snapshot-fresh-signals-v0 --as-of 2025-11-15 --fresh-days 30 --insider-min-value 10000 --top-n 20
sudo docker compose --env-file prod.env exec backend python -m app.cli snapshot-recommendations-v0 --as-of 2025-11-15 --fresh-days 7 --buy-score-threshold 70 --insider-min-value 100000 --top-n 20

# Generate today's subscriber alert draft (no sending unless you click Send in UI)
sudo docker compose --env-file prod.env exec backend python -m app.cli send-daily-subscriber-alerts-v0
