#!/usr/bin/env bash
set -euo pipefail

# WealthPulse daily pipeline wrapper for VM Docker Compose deployments.
# Core logic lives in backend CLI command: run-daily-pipeline-v0

WORKDIR="${WEALTHPULSE_PIPELINE_WORKDIR:-/opt/wealthpulse}"
ENV_FILE="${WEALTHPULSE_PIPELINE_ENV_FILE:-prod.env}"
BACKEND_SERVICE="${WEALTHPULSE_PIPELINE_BACKEND_SERVICE:-backend}"

SEC_LOOKBACK_DAYS="${WEALTHPULSE_PIPELINE_SEC_LOOKBACK_DAYS:-3}"
SEC_LIMIT="${WEALTHPULSE_PIPELINE_SEC_LIMIT:-200}"
TOP_N="${WEALTHPULSE_PIPELINE_TOP_N:-20}"
BOOTSTRAP_13F_IF_MISSING="${WEALTHPULSE_PIPELINE_BOOTSTRAP_13F_IF_MISSING:-true}"

RUN_BACKTEST="${WEALTHPULSE_PIPELINE_RUN_BACKTEST:-true}"
BACKTEST_LOOKBACK_DAYS="${WEALTHPULSE_PIPELINE_BACKTEST_LOOKBACK_DAYS:-120}"

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

AS_OF_UTC="$(date -u +"%Y-%m-%dT%H:%M:%S")"

dc_exec() {
  docker compose --env-file "${ENV_FILE}" exec -T "${BACKEND_SERVICE}" "$@"
}
info "Starting daily pipeline wrapper (as_of=${AS_OF_UTC})"
info "RUN: backend app.cli run-daily-pipeline-v0"

args=(
  python -m app.cli run-daily-pipeline-v0
  --as-of "${AS_OF_UTC}"
  --sec-lookback-days "${SEC_LOOKBACK_DAYS}"
  --sec-limit "${SEC_LIMIT}"
  --top-n "${TOP_N}"
  --backtest-lookback-days "${BACKTEST_LOOKBACK_DAYS}"
)

if [[ "${BOOTSTRAP_13F_IF_MISSING}" == "true" ]]; then
  args+=(--bootstrap-13f-if-missing)
else
  args+=(--no-bootstrap-13f-if-missing)
fi
if [[ "${RUN_REDDIT_INGEST}" == "true" ]]; then
  args+=(--run-reddit-ingest)
else
  args+=(--no-run-reddit-ingest)
fi
if [[ "${RUN_BACKTEST}" == "true" ]]; then
  args+=(--run-backtest)
else
  args+=(--no-run-backtest)
fi

dc_exec "${args[@]}"

info "Daily pipeline wrapper completed successfully."
