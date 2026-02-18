#!/usr/bin/env bash
set -euo pipefail

# One-command status check for VM compose deployments.

WORKDIR="${WEALTHPULSE_PIPELINE_WORKDIR:-/opt/wealthpulse}"
ENV_FILE="${WEALTHPULSE_PIPELINE_ENV_FILE:-prod.env}"
BACKEND_SERVICE="${WEALTHPULSE_PIPELINE_BACKEND_SERVICE:-backend}"
LOOKBACK_DAYS="${WEALTHPULSE_PIPELINE_STATUS_LOOKBACK_DAYS:-7}"
LOG_FILE="${WEALTHPULSE_PIPELINE_LOG_FILE:-/var/log/wealthpulse/daily_pipeline.log}"
TAIL_LINES="${WEALTHPULSE_PIPELINE_STATUS_TAIL_LINES:-80}"

cd "${WORKDIR}"

echo "== docker compose status =="
sudo docker compose --env-file "${ENV_FILE}" ps
echo

echo "== pipeline status (backend CLI) =="
sudo docker compose --env-file "${ENV_FILE}" exec -T "${BACKEND_SERVICE}" \
  python -m app.cli pipeline-status-v0 --lookback-days "${LOOKBACK_DAYS}"
echo

if [[ -f "${LOG_FILE}" ]]; then
  echo "== recent pipeline log (${LOG_FILE}) =="
  sudo tail -n "${TAIL_LINES}" "${LOG_FILE}"
else
  echo "No pipeline log file found at ${LOG_FILE}"
fi
