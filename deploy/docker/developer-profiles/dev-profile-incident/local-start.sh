#!/usr/bin/env bash
set -euo pipefail

# Local, zero-GPU incident-console loop. Secrets stay in the ignored
# incident-console/.env file and are loaded by uv; nothing is exported here.
PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$PROFILE_DIR/../../../.." && pwd)"
ENV_FILE="$PROFILE_DIR/incident-console/.env"
BACKEND_DIR="$PROFILE_DIR/mock-backend/base_profile_mock"

if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Missing environment file: %s\n' "$ENV_FILE" >&2
    exit 1
fi

# uv does not override an inherited value. Remove stale shell/direnv values so
# the ignored file is the single source of truth for this process tree.
unset INCIDENT_DB_DSN

cleanup() {
    if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

cd "$BACKEND_DIR"
PYTHONPATH="$REPO_ROOT/services/agent/src" \
uv run --env-file "$ENV_FILE" \
    uvicorn base_profile_mock.app:create_app \
    --factory --host 127.0.0.1 --port 7777 --reload &
BACKEND_PID=$!

cd "$PROFILE_DIR/incident-console"
uv run streamlit run app.py
