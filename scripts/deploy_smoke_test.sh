#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${WEALTHPULSE_BASE_URL:-http://127.0.0.1}"

echo "Smoke test: ${BASE_URL}"

curl -sSf "${BASE_URL}/health" >/dev/null
echo "OK: /health"

curl -sSf "${BASE_URL}/subscribe" >/dev/null
echo "OK: /subscribe"

code="$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/admin/auth/status" || true)"
if [[ "${code}" != "200" ]]; then
  echo "WARN: /api/admin/auth/status returned HTTP ${code}"
else
  echo "OK: /api/admin/auth/status"
fi

echo "Smoke test done."

