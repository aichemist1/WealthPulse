#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${BASH_VERSION:-}" ]]; then
  echo "This script must be run with bash."
  echo "Run: bash scripts/run_demo_dashboard.sh"
  exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"

DB_PATH="/tmp/wealthpulse_demo.sqlite"
export WEALTHPULSE_DB_URL="sqlite:////tmp/wealthpulse_demo.sqlite"
export PYTHONPATH="${BACKEND_DIR}"

# Default to reusing the demo DB so you don't "lose" data between runs.
# Set WEALTHPULSE_DEMO_RESET_DB=1 to recreate from scratch.
RESET_DB="${WEALTHPULSE_DEMO_RESET_DB:-0}"

BACKEND_PORT_DEFAULT="8000"
FRONTEND_PORT_DEFAULT="5173"
BACKEND_PORT="${WEALTHPULSE_DEMO_BACKEND_PORT:-$BACKEND_PORT_DEFAULT}"
FRONTEND_PORT="${WEALTHPULSE_DEMO_FRONTEND_PORT:-$FRONTEND_PORT_DEFAULT}"

DAY_PREV_DEFAULT="2025-08-14"
DAY_CUR_DEFAULT="2025-11-14"
REPORT_PERIOD_DEFAULT="2025-09-30"
ASOF_DEFAULT="2025-11-15"

DAY_PREV="${WEALTHPULSE_DEMO_DAY_PREV:-$DAY_PREV_DEFAULT}"
DAY_CUR="${WEALTHPULSE_DEMO_DAY_CUR:-$DAY_CUR_DEFAULT}"
REPORT_PERIOD="${WEALTHPULSE_DEMO_REPORT_PERIOD:-$REPORT_PERIOD_DEFAULT}"
ASOF_DATE="${WEALTHPULSE_DEMO_ASOF_DATE:-$ASOF_DEFAULT}"

INGEST_LIMIT_13F="${WEALTHPULSE_DEMO_INGEST_LIMIT_13F:-10}"
INGEST_LIMIT_SC13="${WEALTHPULSE_DEMO_INGEST_LIMIT_SC13:-200}"
INGEST_LIMIT_FORM4="${WEALTHPULSE_DEMO_INGEST_LIMIT_FORM4:-200}"
EVENT_DAYS="${WEALTHPULSE_DEMO_EVENT_DAYS:-5}"
SNAPSHOT_LIMIT="${WEALTHPULSE_DEMO_SNAPSHOT_LIMIT:-50}"
export WEALTHPULSE_SEC_RPS="${WEALTHPULSE_SEC_RPS:-2}"
export WEALTHPULSE_SEC_TIMEOUT_S="${WEALTHPULSE_SEC_TIMEOUT_S:-60}"
export WEALTHPULSE_SEC_RETRIES="${WEALTHPULSE_SEC_RETRIES:-4}"
export WEALTHPULSE_SEC_BACKOFF_S="${WEALTHPULSE_SEC_BACKOFF_S:-1.5}"

if [[ -z "${WEALTHPULSE_SEC_USER_AGENT:-}" ]]; then
  echo "Missing WEALTHPULSE_SEC_USER_AGENT."
  echo "Example:"
  echo "  export WEALTHPULSE_SEC_USER_AGENT='WealthPulse (you@domain.com)'"
  exit 2
fi

echo "Using DB: ${DB_PATH}"
echo "Ingest days: prev=${DAY_PREV} cur=${DAY_CUR}  |  report_period=${REPORT_PERIOD}"
echo "Recommendations as_of: ${ASOF_DATE}"

is_port_free() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
try:
    s.bind(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
else:
    raise SystemExit(0)
finally:
    try:
        s.close()
    except Exception:
        pass
PY
}

find_free_port() {
  local port="$1"
  while ! is_port_free "$port"; do
    port="$((port + 1))"
  done
  echo "$port"
}

BACKEND_PORT="$(find_free_port "$BACKEND_PORT")"
FRONTEND_PORT="$(find_free_port "$FRONTEND_PORT")"
export WEALTHPULSE_CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}"

if [[ -f "${DB_PATH}" ]]; then
  if [[ "${RESET_DB}" == "1" ]]; then
    echo "Resetting demo DB (delete): ${DB_PATH}"
    rm -f "${DB_PATH}"
  else
    echo "Demo DB already exists: ${DB_PATH}"
    echo "Reusing it. Set WEALTHPULSE_DEMO_RESET_DB=1 to recreate from scratch."
  fi
fi

if [[ ! -x "${BACKEND_DIR}/.venv/bin/python" ]]; then
  echo "Creating backend venv..."
  python3 -m venv "${BACKEND_DIR}/.venv"
fi

echo "Installing/updating backend deps..."
"${BACKEND_DIR}/.venv/bin/python" -m pip install -q -r "${BACKEND_DIR}/requirements.txt"

echo "Installing frontend deps (if needed)..."
pushd "${FRONTEND_DIR}" >/dev/null
npm install >/dev/null
popd >/dev/null

echo "Initializing DB..."
pushd "${BACKEND_DIR}" >/dev/null
"${BACKEND_DIR}/.venv/bin/python" -m app.cli init-db

echo "Ingesting 13F filings (small sample)..."
"${BACKEND_DIR}/.venv/bin/python" -m app.cli ingest-13f-edgar --day "${DAY_PREV}" --limit "${INGEST_LIMIT_13F}"
"${BACKEND_DIR}/.venv/bin/python" -m app.cli ingest-13f-edgar --day "${DAY_CUR}" --limit "${INGEST_LIMIT_13F}"

EVENT_DAYS_LIST="$(python3 - <<PY
from datetime import date, timedelta
y, m, d = (int(x) for x in "${DAY_CUR}".split("-"))
start = date(y, m, d)
days = int("${EVENT_DAYS}")
for i in range(max(1, days)):
  print((start - timedelta(days=i)).isoformat())
PY
)"

echo "Ingesting Schedule 13D/13G filings (corroborator; multi-day sample)..."
for day in ${EVENT_DAYS_LIST}; do
  echo "  SC13 day: ${day}"
  if ! "${BACKEND_DIR}/.venv/bin/python" -m app.cli ingest-sc13-edgar --day "${day}" --limit "${INGEST_LIMIT_SC13}"; then
    echo "  WARN: SC13 ingestion failed for ${day} (SEC may be timing out)."
  fi
done

echo "Ingesting Form 4 filings (insider corroborator; multi-day sample)..."
for day in ${EVENT_DAYS_LIST}; do
  echo "  Form4 day: ${day}"
  if ! "${BACKEND_DIR}/.venv/bin/python" -m app.cli ingest-form4-edgar --day "${day}" --limit "${INGEST_LIMIT_FORM4}"; then
    echo "  WARN: Form 4 ingestion failed for ${day} (SEC may be timing out)."
  fi
done

echo "Computing initial 13F whale snapshot..."
"${BACKEND_DIR}/.venv/bin/python" -m app.cli snapshot-13f-whales --report-period "${REPORT_PERIOD}" --limit "${SNAPSHOT_LIMIT}" >/dev/null
popd >/dev/null

TOP_CUSIPS_FILE="/tmp/wealthpulse_demo_top_cusips.txt"
echo "Extracting snapshot CUSIPs -> ${TOP_CUSIPS_FILE}"
pushd "${BACKEND_DIR}" >/dev/null
"${BACKEND_DIR}/.venv/bin/python" - <<'PY' > "${TOP_CUSIPS_FILE}"
from sqlmodel import Session, select
from app.db import create_db_engine
from app.models import Snapshot13FWhale, SnapshotRun

eng = create_db_engine()
with Session(eng) as s:
    run = (
        s.exec(select(SnapshotRun).where(SnapshotRun.kind == "13f_whales").order_by(SnapshotRun.as_of.desc()))
        .first()
    )
    if not run:
        raise SystemExit(2)
    cusips = s.exec(select(Snapshot13FWhale.cusip).where(Snapshot13FWhale.run_id == run.id)).all()
    out = sorted({str(c).upper() for c in cusips if c})
print("\n".join(out))
PY
popd >/dev/null

echo "Enriching top CUSIPs to tickers via OpenFIGI (best-effort)..."
if [[ -z "${WEALTHPULSE_OPENFIGI_API_KEY:-}" ]]; then
  echo "  (No WEALTHPULSE_OPENFIGI_API_KEY set; OpenFIGI may rate-limit. This is optional.)"
fi
pushd "${BACKEND_DIR}" >/dev/null
"${BACKEND_DIR}/.venv/bin/python" -m app.cli enrich-security-map-openfigi \
  --cusips-file "${TOP_CUSIPS_FILE}" \
  --limit 200 \
  --batch-size 10 >/dev/null || true
popd >/dev/null

TOP_TICKERS_FILE="/tmp/wealthpulse_demo_top_tickers.txt"
echo "Extracting mapped tickers -> ${TOP_TICKERS_FILE}"
pushd "${BACKEND_DIR}" >/dev/null
"${BACKEND_DIR}/.venv/bin/python" - <<'PY' > "${TOP_TICKERS_FILE}"
from sqlmodel import Session, select
from app.db import create_db_engine
from app.models import Security

eng = create_db_engine()
with Session(eng) as s:
    tickers = sorted({r.ticker for r in s.exec(select(Security)).all() if r.ticker})
print("\n".join(tickers))
PY
popd >/dev/null

echo "Appending curated watchlists (ETFs + dividends) -> ${TOP_TICKERS_FILE}"
python3 - <<'PY'
from pathlib import Path

path = Path("/tmp/wealthpulse_demo_top_tickers.txt")
existing = {ln.strip().upper() for ln in path.read_text().splitlines() if ln.strip()} if path.exists() else set()
watch = {
    # ETFs / Macro
    "GLD","AIQ","QTUM","SKYY","MAGS","JTEK","ARKW","CHAT","HACK",
    # High-yield dividend stocks (seed list)
    "VNOM","SLB","EOG",
}
merged = sorted(existing | watch)
path.write_text("\n".join(merged) + ("\n" if merged else ""))
print(f"Tickers total: {len(merged)}")
PY

echo "Ingesting prices (trend corroborator; Stooq)..."
pushd "${BACKEND_DIR}" >/dev/null
if ! "${BACKEND_DIR}/.venv/bin/python" -m app.cli ingest-prices-stooq --tickers-file "${TOP_TICKERS_FILE}" --keep-last-days 220 --limit-tickers 50 >/dev/null; then
  echo "WARN: Price ingestion failed. Trend corroborator may be missing."
fi
popd >/dev/null

echo "Fetching dividend metrics (Yahoo; best-effort)..."
pushd "${BACKEND_DIR}" >/dev/null
if ! "${BACKEND_DIR}/.venv/bin/python" -m app.cli ingest-dividend-metrics-yahoo >/dev/null; then
  echo "WARN: Dividend metrics fetch failed. Dividend card will show trend only."
fi
popd >/dev/null

echo "Recomputing 13F whale snapshot (now with tickers where available)..."
echo
pushd "${BACKEND_DIR}" >/dev/null
"${BACKEND_DIR}/.venv/bin/python" -m app.cli snapshot-13f-whales --report-period "${REPORT_PERIOD}" --limit 20 | head
echo
echo "Computing v0 recommendations snapshot..."
"${BACKEND_DIR}/.venv/bin/python" -m app.cli snapshot-recommendations-v0 --as-of "${ASOF_DATE}" --fresh-days 7 --buy-score-threshold 70 --insider-min-value 100000 --top-n 20 >/dev/null || true

echo "Computing v0 fresh whale signals snapshot..."
# Demo-friendly defaults: increase fresh window and lower min insider value so small samples still produce rows.
"${BACKEND_DIR}/.venv/bin/python" -m app.cli snapshot-fresh-signals-v0 --as-of "${ASOF_DATE}" --fresh-days 30 --insider-min-value 10000 --buy-score-threshold 75 --avoid-score-threshold 35 --top-n 20 >/dev/null || true

echo "Generating alerts (v0)..."
"${BACKEND_DIR}/.venv/bin/python" -m app.cli generate-alerts-v0 >/dev/null || true
popd >/dev/null
echo

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Starting backend (uvicorn) on http://127.0.0.1:${BACKEND_PORT} ..."
pushd "${BACKEND_DIR}" >/dev/null
"${BACKEND_DIR}/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" --log-level warning &
BACKEND_PID="$!"
popd >/dev/null

BACKEND_BASE_URL="http://127.0.0.1:${BACKEND_PORT}"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"
echo "Backend URL:  ${BACKEND_BASE_URL}"
echo "Frontend URL: ${FRONTEND_BASE_URL}"

echo "Waiting for backend..."
for _ in $(seq 1 30); do
  if curl -sSf "${BACKEND_BASE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done
curl -sSf "${BACKEND_BASE_URL}/health" >/dev/null

if ! curl -sSf "${BACKEND_BASE_URL}/admin/recommendations/latest" >/dev/null 2>&1; then
  echo "Backend does not expose /admin/recommendations/latest yet."
  echo "Stop any old backend processes and re-run this script."
  exit 2
fi

echo "Starting frontend on http://127.0.0.1:${FRONTEND_PORT} ..."
echo "Press Ctrl+C to stop."
pushd "${FRONTEND_DIR}" >/dev/null
VITE_API_BASE_URL="http://127.0.0.1:${BACKEND_PORT}" npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}" --strictPort
popd >/dev/null
