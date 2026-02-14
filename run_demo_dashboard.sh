#!/usr/bin/env bash
set -euo pipefail

# Convenience wrapper so you can run:
#   ./run_demo_dashboard.sh
#
# The real script lives in scripts/ and must be executed with bash.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/run_demo_dashboard.sh" "$@"

