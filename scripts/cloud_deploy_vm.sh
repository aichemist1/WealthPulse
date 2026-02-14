#!/usr/bin/env bash
set -euo pipefail

# Cloud-agnostic "one-click" VM deploy.
#
# What it does:
# - SSH to a VM (Ubuntu recommended)
# - Installs Docker + Compose plugin if missing (optional)
# - Uploads the repo (excluding heavy/irrelevant dirs)
# - Uploads prod.env
# - Runs: docker compose up -d --build
#
# Usage:
#   cp scripts/cloud_deploy.env.example scripts/cloud_deploy.env
#   chmod 600 scripts/cloud_deploy.env
#   bash scripts/cloud_deploy_vm.sh
#
# You can also override via env vars (see scripts/cloud_deploy.env.example).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${WEALTHPULSE_CLOUD_ENV_FILE:-${ROOT_DIR}/scripts/cloud_deploy.env}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${WEALTHPULSE_VM_HOST:?Set WEALTHPULSE_VM_HOST (VM public IP / hostname)}"
: "${WEALTHPULSE_VM_USER:=ubuntu}"
: "${WEALTHPULSE_VM_SSH_KEY:?Set WEALTHPULSE_VM_SSH_KEY (path to SSH private key)}"
: "${WEALTHPULSE_REMOTE_DIR:=/opt/wealthpulse}"
: "${WEALTHPULSE_INSTALL_DOCKER:=true}"
: "${WEALTHPULSE_LOCAL_PROD_ENV:=${ROOT_DIR}/prod.env}"

SSH_OPTS=(-i "${WEALTHPULSE_VM_SSH_KEY}" -o StrictHostKeyChecking=accept-new)
SSH_TARGET="${WEALTHPULSE_VM_USER}@${WEALTHPULSE_VM_HOST}"

say() { printf "\n==> %s\n" "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1"
    exit 2
  }
}

need ssh
need rsync

if [[ ! -f "${WEALTHPULSE_LOCAL_PROD_ENV}" ]]; then
  echo "Missing ${WEALTHPULSE_LOCAL_PROD_ENV}."
  echo "Create it from ${ROOT_DIR}/prod.env.example and fill values."
  exit 2
fi

say "Connecting to ${SSH_TARGET}"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "echo connected"

if [[ "${WEALTHPULSE_INSTALL_DOCKER}" == "true" ]]; then
  say "Ensuring Docker is installed on VM (Ubuntu)"
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "bash -s" <<'EOF'
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo "Docker + compose already installed."
  exit 0
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo not found; install docker manually."
  exit 2
fi

sudo apt-get update -y
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker "$USER" || true
echo "Docker installed. If docker permissions fail, re-login the SSH session."
EOF
fi

say "Preparing remote directory: ${WEALTHPULSE_REMOTE_DIR}"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "sudo mkdir -p '${WEALTHPULSE_REMOTE_DIR}' && sudo chown -R '${WEALTHPULSE_VM_USER}':'${WEALTHPULSE_VM_USER}' '${WEALTHPULSE_REMOTE_DIR}'"

say "Uploading app (rsync)"
rsync -az --delete \
  --exclude '.git/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'backend/.venv/' \
  --exclude '**/__pycache__/' \
  --exclude '*.db' \
  --exclude '*.sqlite' \
  --exclude 'prod.env' \
  -e "ssh ${SSH_OPTS[*]}" \
  "${ROOT_DIR}/" "${SSH_TARGET}:${WEALTHPULSE_REMOTE_DIR}/"

say "Uploading prod.env"
rsync -az -e "ssh ${SSH_OPTS[*]}" "${WEALTHPULSE_LOCAL_PROD_ENV}" "${SSH_TARGET}:${WEALTHPULSE_REMOTE_DIR}/prod.env"

say "Starting stack (docker compose up -d --build)"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${WEALTHPULSE_REMOTE_DIR}' && docker compose --env-file prod.env up -d --build"

say "Smoke test (from VM)"
ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "cd '${WEALTHPULSE_REMOTE_DIR}' && WEALTHPULSE_BASE_URL='http://127.0.0.1' bash scripts/deploy_smoke_test.sh"

say "Done"
echo "Open:"
echo "  Admin UI:     http://${WEALTHPULSE_VM_HOST}/"
echo "  Subscribe:    http://${WEALTHPULSE_VM_HOST}/subscribe"
echo
echo "If emails contain unreachable links, ensure in prod.env:"
echo "  WEALTHPULSE_PUBLIC_BASE_URL=http://${WEALTHPULSE_VM_HOST}"

