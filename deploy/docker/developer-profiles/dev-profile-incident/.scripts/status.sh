#!/usr/bin/env bash
#
# status.sh — Report deploy status of Docker appliance containers AND native
# processes on kwanz-ws.
#
# Runs on the VM against the local docker daemon and native process manager.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

echo "=== Docker Appliance Containers (mdx) ==="
(cd "$REPO_ROOT/deploy/docker" && docker compose -p mdx ps)

echo ""
"${SCRIPT_DIR}/native-services.sh" status
