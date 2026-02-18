#!/usr/bin/env bash
set -euo pipefail

# WealthPulse daily pipeline for VM Docker Compose deployments.
# Purpose: refresh ingestion + snapshots + daily artifact + draft alerts.

WORKDIR="${WEALTHPULSE_PIPELINE_WORKDIR:-/opt/wealthpulse}"
ENV_FILE="${WEALTHPULSE_PIPELINE_ENV_FILE:-prod.env}"
BACKEND_SERVICE="${WEALTHPULSE_PIPELINE_BACKEND_SERVICE:-backend}"

FORM4_DAYS_BACK="${WEALTHPULSE_PIPELINE_FORM4_DAYS_BACK:-1}"
SC13_DAYS_BACK="${WEALTHPULSE_PIPELINE_SC13_DAYS_BACK:-1}"
FORM4_LIMIT="${WEALTHPULSE_PIPELINE_FORM4_LIMIT:-200}"
SC13_LIMIT="${WEALTHPULSE_PIPELINE_SC13_LIMIT:-200}"

FRESH_DAYS="${WEALTHPULSE_PIPELINE_FRESH_DAYS:-30}"
FRESH_TOP_N="${WEALTHPULSE_PIPELINE_FRESH_TOP_N:-20}"
FRESH_INSIDER_MIN_VALUE="${WEALTHPULSE_PIPELINE_FRESH_INSIDER_MIN_VALUE:-10000}"

RECS_FRESH_DAYS="${WEALTHPULSE_PIPELINE_RECS_FRESH_DAYS:-7}"
RECS_TOP_N="${WEALTHPULSE_PIPELINE_RECS_TOP_N:-20}"
RECS_BUY_THRESHOLD="${WEALTHPULSE_PIPELINE_RECS_BUY_THRESHOLD:-70}"
RECS_INSIDER_MIN_VALUE="${WEALTHPULSE_PIPELINE_RECS_INSIDER_MIN_VALUE:-100000}"

RUN_BACKTEST="${WEALTHPULSE_PIPELINE_RUN_BACKTEST:-true}"
BACKTEST_LOOKBACK_DAYS="${WEALTHPULSE_PIPELINE_BACKTEST_LOOKBACK_DAYS:-120}"
BACKTEST_HORIZONS="${WEALTHPULSE_PIPELINE_BACKTEST_HORIZONS:-5,20}"
BACKTEST_TOP_N="${WEALTHPULSE_PIPELINE_BACKTEST_TOP_N:-5}"
BACKTEST_BASELINE="${WEALTHPULSE_PIPELINE_BACKTEST_BASELINE:-SPY}"

RUN_REDDIT_INGEST="${WEALTHPULSE_PIPELINE_RUN_REDDIT_INGEST:-false}"

LOG_DIR="${WEALTHPULSE_PIPELINE_LOG_DIR:-/var/log/wealthpulse}"
mkdir -p "${LOG_DIR}"
LOG_FILE="${WEALTHPULSE_PIPELINE_LOG_FILE:-${LOG_DIR}/daily_pipeline.log}"
exec >>"${LOG_FILE}" 2>&1

timestamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
info() { echo "[$(timestamp)] INFO  $*"; }
warn() { echo "[$(timestamp)] WARN  $*"; }
err() { echo "[$(timestamp)] ERROR $*"; }

if [[ ! -d "${WORKDIR}" ]]; then
  err "Workdir not found: ${WORKDIR}"
  exit 2
fi
if [[ ! -f "${WORKDIR}/${ENV_FILE}" ]]; then
  err "Env file not found: ${WORKDIR}/${ENV_FILE}"
  exit 2
fi

cd "${WORKDIR}"

if ! command -v docker >/dev/null 2>&1; then
  err "docker command not found"
  exit 2
fi

if ! docker compose --env-file "${ENV_FILE}" ps "${BACKEND_SERVICE}" >/dev/null 2>&1; then
  err "docker compose backend service not reachable (service=${BACKEND_SERVICE})"
  exit 2
fi

TODAY_UTC="$(date -u +%F)"
AS_OF_UTC="$(date -u +"%Y-%m-%dT%H:%M:%S")"
FORM4_DAY="$(date -u -d "${FORM4_DAYS_BACK} day ago" +%F)"
SC13_DAY="$(date -u -d "${SC13_DAYS_BACK} day ago" +%F)"
BACKTEST_START="$(date -u -d "${BACKTEST_LOOKBACK_DAYS} day ago" +%F)"

dc_exec() {
  docker compose --env-file "${ENV_FILE}" exec -T "${BACKEND_SERVICE}" "$@"
}

run_required() {
  info "RUN (required): $*"
  "$@"
}

run_best_effort() {
  info "RUN (best-effort): $*"
  if ! "$@"; then
    warn "Command failed (continuing): $*"
    return 1
  fi
  return 0
}

info "Starting daily pipeline (as_of=${AS_OF_UTC}, today=${TODAY_UTC})"

run_required dc_exec python -m app.cli init-db

# Ingestion (best-effort due SEC throttling/timeouts)
run_best_effort dc_exec python -m app.cli ingest-form4-edgar --day "${FORM4_DAY}" --limit "${FORM4_LIMIT}"
run_best_effort dc_exec python -m app.cli ingest-sc13-edgar --day "${SC13_DAY}" --limit "${SC13_LIMIT}"

if [[ "${RUN_REDDIT_INGEST}" == "true" ]]; then
  run_best_effort dc_exec python -m app.cli ingest-social-reddit --lookback-hours 24
fi

# Snapshots and artifacts
run_required dc_exec python -m app.cli snapshot-fresh-signals-v0 \
  --as-of "${AS_OF_UTC}" \
  --fresh-days "${FRESH_DAYS}" \
  --insider-min-value "${FRESH_INSIDER_MIN_VALUE}" \
  --top-n "${FRESH_TOP_N}"

run_required dc_exec python -m app.cli snapshot-recommendations-v0 \
  --as-of "${AS_OF_UTC}" \
  --fresh-days "${RECS_FRESH_DAYS}" \
  --buy-score-threshold "${RECS_BUY_THRESHOLD}" \
  --insider-min-value "${RECS_INSIDER_MIN_VALUE}" \
  --top-n "${RECS_TOP_N}"

run_required dc_exec python -m app.cli snapshot-daily-artifact-v0 --as-of "${AS_OF_UTC}"

if [[ "${RUN_BACKTEST}" == "true" ]]; then
  run_best_effort dc_exec python -m app.cli backtest-snapshots-v0 \
    --start-as-of "${BACKTEST_START}" \
    --end-as-of "${TODAY_UTC}" \
    --baseline-ticker "${BACKTEST_BASELINE}" \
    --horizons "${BACKTEST_HORIZONS}" \
    --top-n-per-action "${BACKTEST_TOP_N}"
fi

# Manual-only product flow: generate draft; admin decides send.
run_required dc_exec python -m app.cli send-daily-subscriber-alerts-v0 --as-of "${AS_OF_UTC}"

info "Daily pipeline completed successfully."
