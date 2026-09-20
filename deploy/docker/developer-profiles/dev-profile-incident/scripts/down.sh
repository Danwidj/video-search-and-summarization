#!/usr/bin/env bash
#
# down.sh — Stop both native VM services and the `mdx` compose stack WITHOUT
# wiping the model-weight cache.
#
# Deliberately never `-v`: dev-profile.sh's own `down` runs
# `docker compose -p mdx down -v --remove-orphans` and then deletes the whole
# data directory, which is exactly the ~35GB-of-NIM/RTVI-cache-loss behavior
# this project's own docs tell you to avoid.
#
# Runs on the VM against the local process manager and docker daemon.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

echo "=== Stopping Native Services ==="
"${SCRIPT_DIR}/native-services.sh" stop

echo ""
echo "=== Stopping Docker Containers (mdx) ==="
(cd "$REPO_ROOT/deploy/docker" && docker compose -p mdx down --remove-orphans)

echo "=== All services stopped ==="
