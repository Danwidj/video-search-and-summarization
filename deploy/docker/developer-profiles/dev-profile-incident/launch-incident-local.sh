#!/usr/bin/env bash
#
# launch-incident-local.sh - open the incident-console local-dev loop in Ghostty.
#
# Opens two new Ghostty windows on your laptop (macOS only):
#   1. Tunnel window: sources deploy/dotfiles/aliases.sh and runs
#      mdx-tunnel-incident, the merged 5-port SSH tunnel to kwanz-ws
#      (agent :8000, LLM :30081, VLM :30082, ingress :7777, console :8501).
#      Leave it running; Ctrl-C closes it.
#   2. UI window: runs the console locally per incident-console/README.md
#      ("Real backend on kwanz-ws via SSH tunnel", Phase 4):
#      cd incident-console && uv sync && uv run streamlit run app.py
#      --server.port 8502 (:8502, so it never clashes with the tunnel's
#      :8501 forward for the VM-hosted console),
#      talking to the VM backend through the tunnel. DB/R2/URLs come from
#      your untracked incident-console/.env.local (see that README).
#
# Mechanism: Ghostty has no macOS CLI for opening windows (`+new-window`
# is unsupported on macOS - see `ghostty --help`), so this drives its
# AppleScript dictionary instead (`new surface configuration` /
# `new window with configuration`, Ghostty >= 1.3.0, verified against the
# installed Ghostty.sdef and Ghostty's own AppleScript docs). Commands are
# fed via each config's `initial input`, the documented way to type into a
# fresh terminal.
#
# Notes:
# - The tunnel also forwards :8501 for the VM-hosted console
#   (DEPLOY_NOTES.md flow: open http://localhost:8501 in a browser).
#   The locally-run Streamlit therefore uses :8502 (--server.port 8502)
#   so the two consoles never fight over :8501. Open the local one at
#   http://localhost:8502 and the VM-hosted one at http://localhost:8501.
# - Both windows set `wait after command` so a fast failure (ssh down,
#   missing DSN) stays visible instead of flashing closed.
# - Only syntax-checked here (bash -n, osacompile); window-spawning was
#   NOT tested end-to-end from this non-interactive checkout.
#
# Usage: bash deploy/docker/developer-profiles/dev-profile-incident/launch-incident-local.sh
#        (run from anywhere; the repo root is derived from this script's
#        own location, so the UI always runs from your local checkout)

set -euo pipefail

# Repo root = the checkout containing this script, so the UI always runs
# from your local tree even when invoked via a symlink or from an odd cwd.
# This script lives 4 levels below repo root (deploy/docker/developer-profiles/
# dev-profile-incident/), hence ../../../../.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
ALIASES="$REPO_ROOT/deploy/dotfiles/aliases.sh"
CONSOLE_DIR="$REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/incident-console"

# --- preflight ---------------------------------------------------------------
if ! command -v osascript >/dev/null 2>&1; then
    echo "launch-incident-local: osascript not found - this script is macOS-only." >&2
    exit 1
fi
if [ ! -d /Applications/Ghostty.app ] && [ ! -d "$HOME/Applications/Ghostty.app" ]; then
    echo "launch-incident-local: Ghostty.app not found - install Ghostty first." >&2
    exit 1
fi
for f in "$ALIASES" "$CONSOLE_DIR/app.py"; do
    [ -e "$f" ] || { echo "launch-incident-local: missing $f - wrong checkout?" >&2; exit 1; }
done
if ! command -v uv >/dev/null 2>&1; then
    echo "launch-incident-local: warning: 'uv' not on PATH - the UI window will fail; install uv first." >&2
fi

TUNNEL_CMD="source '$ALIASES' && mdx-tunnel-incident"
UI_CMD="cd '$CONSOLE_DIR' && uv sync && uv run streamlit run app.py --server.port 8502"

osascript <<EOF
tell application "Ghostty"
    activate

    set tunnelCfg to new surface configuration
    set initial working directory of tunnelCfg to "$REPO_ROOT"
    set initial input of tunnelCfg to "$TUNNEL_CMD" & linefeed
    set wait after command of tunnelCfg to true
    new window with configuration tunnelCfg

    set uiCfg to new surface configuration
    set initial working directory of uiCfg to "$CONSOLE_DIR"
    set initial input of uiCfg to "$UI_CMD" & linefeed
    set wait after command of uiCfg to true
    new window with configuration uiCfg
end tell
EOF

cat <<EOF
Launched two Ghostty windows: tunnel (mdx-tunnel-incident) + local console (:8502).
Next: run mdx-tunnel-incident-check once the tunnel is up, then open the
local Streamlit at http://localhost:8502 - or open the VM-hosted
console directly at http://localhost:8501 through the tunnel.
EOF
