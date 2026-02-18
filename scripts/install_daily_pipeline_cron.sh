#!/usr/bin/env bash
set -euo pipefail

# Installs (or updates) a weekday cron entry for WealthPulse daily pipeline.
# Default schedule: 13:35 UTC weekdays (~8:35 AM US Central during standard time).

WORKDIR="${WEALTHPULSE_PIPELINE_WORKDIR:-/opt/wealthpulse}"
PIPELINE_SCRIPT="${WEALTHPULSE_PIPELINE_SCRIPT:-${WORKDIR}/scripts/pipeline_daily_compose.sh}"
SCHEDULE="${WEALTHPULSE_PIPELINE_CRON_SCHEDULE:-35 13 * * 1-5}"

MARKER="# wealthpulse-daily-pipeline"
CRON_LINE="${SCHEDULE} cd ${WORKDIR} && ${PIPELINE_SCRIPT} ${MARKER}"

tmp="$(mktemp)"
trap 'rm -f "${tmp}"' EXIT

crontab -l 2>/dev/null | grep -v "${MARKER}" > "${tmp}" || true
echo "${CRON_LINE}" >> "${tmp}"
crontab "${tmp}"

echo "Installed cron entry:"
echo "${CRON_LINE}"
echo
echo "Current crontab:"
crontab -l
