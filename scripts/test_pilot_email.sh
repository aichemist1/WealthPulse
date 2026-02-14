#!/usr/bin/env bash
set -euo pipefail

# Pilot email test helper.
#
# IMPORTANT (Gmail):
# - Use a Google "App Password" (recommended), not your normal Gmail password.
# - Sender and receiver can be the same address for a quick test.
#
# Usage:
#   bash scripts/test_pilot_email.sh
#
# Optional overrides:
#   WEALTHPULSE_TEST_EMAIL='you@gmail.com' bash scripts/test_pilot_email.sh
#   WEALTHPULSE_DB_URL='sqlite:////tmp/wealthpulse_demo.sqlite' bash scripts/test_pilot_email.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EMAIL="${WEALTHPULSE_TEST_EMAIL:-cloudsolutions.sk@gmail.com}"

export WEALTHPULSE_SMTP_HOST="${WEALTHPULSE_SMTP_HOST:-smtp.gmail.com}"
export WEALTHPULSE_SMTP_PORT="${WEALTHPULSE_SMTP_PORT:-587}"
export WEALTHPULSE_SMTP_USE_STARTTLS="${WEALTHPULSE_SMTP_USE_STARTTLS:-true}"
export WEALTHPULSE_SMTP_USER="${WEALTHPULSE_SMTP_USER:-$EMAIL}"
export WEALTHPULSE_SMTP_FROM_EMAIL="${WEALTHPULSE_SMTP_FROM_EMAIL:-$EMAIL}"
export WEALTHPULSE_PUBLIC_BASE_URL="${WEALTHPULSE_PUBLIC_BASE_URL:-http://localhost:8000}"

# Use the demo DB by default so it can reuse your existing snapshot data.
export WEALTHPULSE_DB_URL="${WEALTHPULSE_DB_URL:-sqlite:////tmp/wealthpulse_demo.sqlite}"

if [[ -z "${WEALTHPULSE_SMTP_PASSWORD:-}" ]]; then
  read -r -s -p "Gmail app password for ${WEALTHPULSE_SMTP_USER}: " WEALTHPULSE_SMTP_PASSWORD
  echo
  export WEALTHPULSE_SMTP_PASSWORD
fi

echo "DB: ${WEALTHPULSE_DB_URL}"
echo "Sender: ${WEALTHPULSE_SMTP_FROM_EMAIL}"
echo "Recipient: ${EMAIL}"

pushd "${ROOT_DIR}/backend" >/dev/null

python -m app.cli init-db >/dev/null

echo
echo "1) Sending confirm email..."
python -m app.cli subscribe-email --email "${EMAIL}"

echo
echo "2) Activating subscriber (pilot shortcut)..."
python -m app.cli admin-activate-subscriber --email "${EMAIL}"

echo
echo "3) Sending daily alert email (limit 1)..."
python -m app.cli send-daily-subscriber-alerts-v0 --limit-subscribers 1 --send

popd >/dev/null

echo
echo "Done. Check inbox/spam for the confirmation + daily signals emails."
