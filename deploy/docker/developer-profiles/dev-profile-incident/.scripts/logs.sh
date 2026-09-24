#!/usr/bin/env bash
#
# logs.sh — Tail logs for one service (native process or Docker container).
# Defaults to `vss-agent` (which runs natively).
#
# Usage: ./logs.sh [service-or-container-name]
# Runs on the VM.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
RUN_DIR="${VSS_RUN_DIR:-${REPO_ROOT}/.run}"

TARGET="${1:-vss-agent}"
shift || true

# Native service log check
if [ -f "${RUN_DIR}/${TARGET}.log" ] || [[ "${TARGET}" =~ ^(vss-agent|video-analytics-api|behavior-analytics)$ ]]; then
  echo "--- Tailing native logs for ${TARGET} (${RUN_DIR}/${TARGET}.log) ---"
  exec "${SCRIPT_DIR}/native-services.sh" logs "${TARGET}" "$@"
else
  echo "--- Tailing Docker container logs for ${TARGET} ---"
  exec docker logs -f --tail=100 "${TARGET}" "$@"
fi
