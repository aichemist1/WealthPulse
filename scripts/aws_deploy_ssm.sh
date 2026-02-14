#!/usr/bin/env bash
set -euo pipefail

# AWS SSM deploy helper (no inbound SSH).
#
# Usage:
#   cp scripts/aws_deploy_ssm.env.example scripts/aws_deploy_ssm.env
#   chmod 600 scripts/aws_deploy_ssm.env
#   bash scripts/aws_deploy_ssm.sh
#
# Notes:
# - This script uploads prod.env content via SSM command payload (base64).
#   For higher security later, move secrets to SSM Parameter Store / Secrets Manager.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${WEALTHPULSE_AWS_ENV_FILE:-${ROOT_DIR}/scripts/aws_deploy_ssm.env}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

: "${AWS_PROFILE:?Set AWS_PROFILE}"
: "${AWS_REGION:?Set AWS_REGION}"
: "${WEALTHPULSE_AWS_INSTANCE_ID:?Set WEALTHPULSE_AWS_INSTANCE_ID}"
: "${WEALTHPULSE_REPO_URL:?Set WEALTHPULSE_REPO_URL (HTTPS repo URL)}"
: "${WEALTHPULSE_REPO_BRANCH:=main}"
: "${WEALTHPULSE_REMOTE_DIR:=/opt/wealthpulse}"
: "${WEALTHPULSE_LOCAL_PROD_ENV:=${ROOT_DIR}/prod.env}"
: "${WEALTHPULSE_INSTALL_DOCKER:=true}"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1"; exit 2; }
}

need aws
need base64
need git

if [[ ! -f "${WEALTHPULSE_LOCAL_PROD_ENV}" ]]; then
  echo "Missing ${WEALTHPULSE_LOCAL_PROD_ENV}."
  echo "Create it from ${ROOT_DIR}/prod.env.example and fill values."
  exit 2
fi

# SSM deploy pulls code from GitHub on the instance, so ensure local repo changes are pushed.
if [[ -d "${ROOT_DIR}/.git" ]]; then
  if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain)" ]]; then
    echo "ERROR: local repo has uncommitted changes."
    echo "SSM deploy pulls from GitHub; commit and push first (or use the SSH/rsync deploy script)."
    exit 2
  fi
  # If upstream is configured, ensure we're not ahead.
  if git -C "${ROOT_DIR}" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git -C "${ROOT_DIR}" fetch -q || true
    ahead="$(git -C "${ROOT_DIR}" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
    if [[ "${ahead}" != "0" ]]; then
      echo "ERROR: local branch is ahead of its upstream by ${ahead} commit(s)."
      echo "SSM deploy pulls from GitHub; push first (or use the SSH/rsync deploy script)."
      exit 2
    fi
  fi
fi

say() { printf "\n==> %s\n" "$*"; }

aws_cmd() {
  AWS_PROFILE="${AWS_PROFILE}" AWS_REGION="${AWS_REGION}" aws "$@"
}

say "Checking instance is managed by SSM: ${WEALTHPULSE_AWS_INSTANCE_ID}"
if ! aws_cmd ssm describe-instance-information --filters "Key=InstanceIds,Values=${WEALTHPULSE_AWS_INSTANCE_ID}" >/dev/null; then
  echo "ERROR: cannot query SSM instance information. Check AWS_PROFILE/AWS_REGION and permissions."
  exit 2
fi

inst_count="$(aws_cmd ssm describe-instance-information --filters "Key=InstanceIds,Values=${WEALTHPULSE_AWS_INSTANCE_ID}" --query "length(InstanceInformationList)" --output text)"
if [[ "${inst_count}" == "0" ]]; then
  echo "ERROR: instance is not managed by SSM yet."
  echo "Fix: attach IAM role AmazonSSMManagedInstanceCore + ensure SSM agent + outbound access."
  exit 2
fi

say "Encoding prod.env for upload"
ENV_B64="$(base64 < "${WEALTHPULSE_LOCAL_PROD_ENV}" | tr -d '\n')"

say "Building remote deploy script"
INSTALL_DOCKER_LINE="false"
if [[ "${WEALTHPULSE_INSTALL_DOCKER}" == "true" ]]; then
  INSTALL_DOCKER_LINE="true"
fi

REMOTE_BODY="$(
  python3 - <<'PY'
print(r'''#!/usr/bin/env bash
set -euo pipefail

echo "Deploying WealthPulse to ${REMOTE_DIR}"

ME="$(id -un 2>/dev/null || echo root)"
GRP="$(id -gn 2>/dev/null || echo root)"

if [[ "${INSTALL_DOCKER}" == "true" ]]; then
  if command -v docker >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1; then
    echo "Docker already installed."
  else
    if ! command -v sudo >/dev/null 2>&1; then
      echo "sudo not found; install docker manually."
      exit 2
    fi

    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update -y
      sudo apt-get install -y ca-certificates curl gnupg lsb-release git

      sudo install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
      sudo chmod a+r /etc/apt/keyrings/docker.gpg

      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
      sudo apt-get update -y
      sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y docker git curl
      sudo dnf install -y docker-compose-plugin || true
    elif command -v yum >/dev/null 2>&1; then
      sudo yum install -y docker git curl
    else
      echo "Unsupported OS package manager. Install docker manually."
      exit 2
    fi

    if command -v systemctl >/dev/null 2>&1; then
      sudo systemctl enable --now docker || true
      sudo systemctl start docker || true
    elif command -v service >/dev/null 2>&1; then
      sudo service docker start || true
    fi

    if ! sudo docker compose version >/dev/null 2>&1; then
      sudo mkdir -p /usr/local/lib/docker/cli-plugins
      arch="$(uname -m)"
      case "$arch" in
        x86_64|amd64) arch="x86_64" ;;
        aarch64|arm64) arch="aarch64" ;;
      esac
      sudo curl -fsSL "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-${arch}" -o /usr/local/lib/docker/cli-plugins/docker-compose
      sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    fi
  fi
fi

sudo mkdir -p "${REMOTE_DIR}"
sudo chown -R "${ME}:${GRP}" "${REMOTE_DIR}"

if [[ ! -d "${REMOTE_DIR}/.git" ]]; then
  rm -rf "${REMOTE_DIR:?}"/*
  git clone --depth 1 --branch "${REPO_BRANCH}" "${REPO_URL}" "${REMOTE_DIR}"
else
  cd "${REMOTE_DIR}"
  git fetch --all --prune
  git reset --hard "origin/${REPO_BRANCH}"
fi

cd "${REMOTE_DIR}"

echo "${ENV_B64}" | base64 -d > prod.env
chmod 600 prod.env

if [[ ! -f docker-compose.yml ]]; then
  echo "ERROR: docker-compose.yml not found in ${REMOTE_DIR}."
  echo "This usually means the instance pulled an older version of the repo."
  echo "Push your latest changes to GitHub and re-run the deploy."
  echo
  pwd || true
  ls -la || true
  exit 14
fi

sudo docker compose --env-file prod.env up -d --build

WEALTHPULSE_BASE_URL="http://127.0.0.1" bash scripts/deploy_smoke_test.sh
echo "Deploy done."
''')
PY
)"

REMOTE_HEADER="$(
  REMOTE_DIR="${WEALTHPULSE_REMOTE_DIR}" \
  REPO_URL="${WEALTHPULSE_REPO_URL}" \
  REPO_BRANCH="${WEALTHPULSE_REPO_BRANCH}" \
  INSTALL_DOCKER="${INSTALL_DOCKER_LINE}" \
  ENV_B64="${ENV_B64}" \
  python3 - <<'PY'
import os, shlex
for k in ["REMOTE_DIR", "REPO_URL", "REPO_BRANCH", "INSTALL_DOCKER", "ENV_B64"]:
    v = os.environ.get(k, "")
    print(f"{k}={shlex.quote(v)}")
PY
)"

REMOTE_SCRIPT="${REMOTE_HEADER}"$'\n'"${REMOTE_BODY}"

REMOTE_SCRIPT_B64="$(printf "%s" "${REMOTE_SCRIPT}" | base64 | tr -d '\n')"

say "Sending deploy command via SSM"
cmd_id="$(
  aws_cmd ssm send-command \
    --document-name "AWS-RunShellScript" \
    --instance-ids "${WEALTHPULSE_AWS_INSTANCE_ID}" \
    --comment "WealthPulse deploy (compose up)" \
    --parameters "$(
      python3 - <<PY
import json
cmds = [
  "set -euo pipefail",
  "echo '${REMOTE_SCRIPT_B64}' | base64 -d > /tmp/wealthpulse_deploy.sh",
  "chmod +x /tmp/wealthpulse_deploy.sh",
  "bash /tmp/wealthpulse_deploy.sh",
]
print(json.dumps({"commands": cmds}))
PY
    )" \
    --query "Command.CommandId" --output text
)"

echo "CommandId: ${cmd_id}"

say "Waiting for SSM command to finish"
for _ in $(seq 1 120); do
  status="$(aws_cmd ssm get-command-invocation --command-id "${cmd_id}" --instance-id "${WEALTHPULSE_AWS_INSTANCE_ID}" --query "Status" --output text 2>/dev/null || true)"
  case "${status}" in
    Success)
      echo "SSM: Success"
      break
      ;;
    Failed|Cancelled|TimedOut)
      echo "SSM: ${status}"
      aws_cmd ssm get-command-invocation --command-id "${cmd_id}" --instance-id "${WEALTHPULSE_AWS_INSTANCE_ID}" --query "StandardErrorContent" --output text || true
      exit 2
      ;;
    InProgress|Pending|Delayed|"")
      sleep 5
      ;;
    *)
      echo "SSM: ${status}"
      sleep 5
      ;;
  esac
done

say "Done"
echo "Open:"
echo "  Admin UI:  http://<EC2_PUBLIC_IP>/"
echo "  Subscribe: http://<EC2_PUBLIC_IP>/subscribe"
echo
echo "Make sure prod.env contains:"
echo "  WEALTHPULSE_PUBLIC_BASE_URL=http://<EC2_PUBLIC_IP>"
