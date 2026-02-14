# WealthPulse Backend (v0)

FastAPI + SQLite backend for ingestion, scoring, and daily snapshot generation.

## Quickstart

1) Create a virtualenv and install deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### One-command demo (ingest + UI)

From repo root:

```bash
export WEALTHPULSE_SEC_USER_AGENT="WealthPulse (you@domain.com)"
bash scripts/run_demo_dashboard.sh
```

If ports are busy, the script automatically picks the next available.

2) Initialize the DB:

```bash
python -m app.cli init-db
```

3) Run the API:

```bash
uvicorn app.main:app --reload
```

## Local Form 4 ingestion (dev)

```bash
python -m app.cli ingest-form4-xml path/to/form4.xml
```

## SEC EDGAR Form 4 ingestion (daily index)

Set a descriptive SEC User-Agent (required):

```bash
export WEALTHPULSE_SEC_USER_AGENT="WealthPulse (your-email@domain.com)"
```

Optionally restrict to a ticker universe file (newline-delimited tickers, e.g. S&P 500):

```bash
python -m app.cli ingest-form4-edgar --day 2026-02-10 --universe-file sp500.txt
```

## SEC EDGAR 13F ingestion (institutional holdings / “whales”)

```bash
export WEALTHPULSE_SEC_USER_AGENT="WealthPulse (your-email@domain.com)"
python -m app.cli ingest-13f-edgar --day 2026-02-14
```

## Import CUSIP↔ticker mapping (needed for S&P 500 filtering)

```bash
python -m app.cli import-security-map backend/data/security_map.example.csv
```

## Bootstrap S&P 500 tickers (public CSV)

This downloads a public constituents CSV (default URL is configurable via `WEALTHPULSE_SP500_CONSTITUENTS_CSV_URL`)
and writes a newline-delimited ticker list.

```bash
python -m app.cli fetch-sp500-tickers --out sp500_tickers.txt
```

## Enrich CUSIP→ticker via OpenFIGI (optional)

OpenFIGI helps map 13F CUSIPs to tickers. It may rate-limit anonymous requests, so an API key is recommended.

```bash
export WEALTHPULSE_OPENFIGI_API_KEY="..."
python -m app.cli enrich-security-map-openfigi --limit 200
```

## “Whale buy” quick report (largest insider purchases)

```bash
python -m app.cli report-insider-buys --min-value 250000 --limit 25
```

## “Whale buys” snapshot (aggregated by ticker)

```bash
python -m app.cli snapshot-insider-whales --as-of 2026-02-11 --window-days 7 --min-value 250000
```

## 13F whale snapshot (quarter-over-quarter, by CUSIP)

```bash
python -m app.cli snapshot-13f-whales --report-period 2025-12-31 --limit 50
```

Optionally restrict by CUSIP universe (newline-delimited):

```bash
python -m app.cli snapshot-13f-whales --report-period 2025-12-31 --universe-cusips-file sp500_cusips.txt
```

Or restrict by ticker universe (requires mapping import above):

```bash
python -m app.cli snapshot-13f-whales --report-period 2025-12-31 --universe-tickers-file sp500_tickers.txt
```
