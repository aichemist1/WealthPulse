#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${WEALTHPULSE_PILOT_ENV_FILE:-${ROOT_DIR}/scripts/pilot.env}"

usage() {
  cat <<'EOF'
WealthPulse pilot helper (loads scripts/pilot.env so you don't retype env vars)

Setup:
  cp scripts/pilot.env.example scripts/pilot.env
  chmod 600 scripts/pilot.env

Commands:
  dashboard              Run the demo dashboard (ingest + snapshots + UI)
  email [to_email]       Subscribe + activate + send 1 daily email to to_email (default: smtp user)
  status                 List subscribers
  policy                 Show subscriber alert thresholds (DB)

Examples:
  bash scripts/pilot.sh dashboard
  bash scripts/pilot.sh email cloudsolutions.sk@gmail.com
  bash scripts/pilot.sh status
EOF
}

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Missing env file: ${ENV_FILE}"
    echo "Create it from: ${ROOT_DIR}/scripts/pilot.env.example"
    exit 2
  fi
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
}

cmd="${1:-}"
if [[ -z "${cmd}" || "${cmd}" == "-h" || "${cmd}" == "--help" ]]; then
  usage
  exit 0
fi
shift || true

load_env

case "${cmd}" in
  dashboard)
    cd "${ROOT_DIR}"
    bash scripts/run_demo_dashboard.sh
    ;;
  email)
    to="${1:-${WEALTHPULSE_SMTP_USER:-}}"
    if [[ -z "${to}" ]]; then
      echo "Missing to_email."
      exit 2
    fi
    cd "${ROOT_DIR}/backend"
    python -m app.cli subscribe-email --email "${to}"
    python -m app.cli admin-activate-subscriber --email "${to}"
    # Pilot convenience: send immediately to validate SMTP, even though the product flow is manual-only in the dashboard.
    python -m app.cli send-daily-subscriber-alerts-v0 --limit-subscribers 1 --send
    echo
    echo "Delivery log:"
    python -m app.cli list-alert-deliveries --limit 20
    ;;
  status)
    cd "${ROOT_DIR}/backend"
    python -m app.cli list-subscribers
    ;;
  policy)
    cd "${ROOT_DIR}/backend"
    python -m app.cli get-subscriber-alert-policy-v0
    ;;
  *)
    echo "Unknown command: ${cmd}"
    usage
    exit 2
    ;;
esac
