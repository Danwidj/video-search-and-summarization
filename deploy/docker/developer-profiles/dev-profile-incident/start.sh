#!/usr/bin/env bash
#
# start.sh — the one-command daily entry point for the incident-console
# workflow. RUN FROM YOUR LAPTOP:
#
#   cd deploy/docker/developer-profiles/dev-profile-incident && ./start.sh
#
# It gets the backend, the SSH tunnel, and the local console all going:
#
#   1. Checks the current deploy state over SSH against the VM
#      (equivalent of the old `mdx-ps` alias — `docker compose -p mdx ps`
#      on the mdx compose project).
#   2. Branches on that state:
#        - NOTHING expected running  -> deploy the backend fresh over SSH
#          (the incident profile's own deploy path: direct
#          `docker compose -f compose.yml --env-file
#          developer-profiles/dev-profile-incident/generated.env.remote
#          up -d` — dev-profile.sh has NO incident profile, see
#          docs/incident-plan/incident-plan-implementation-remote.md §2),
#          then open the tunnel, then start the console.
#        - EVERYTHING expected up    -> skip the deploy, straight to
#          tunnel + console.
#        - PARTIAL (some up)         -> STOP. Prints what's up vs. what's
#          missing/expected and exits nonzero. This is a deliberate captain
#          decision: never auto-reconcile, auto-clean, or force a redeploy
#          over a partial state. Clear it manually (e.g. run down.sh on
#          kwanz-ws) and re-run.
#   3. The tunnel step is laptop-side only (same hostname guard the old
#      `mdx-tunnel-incident` alias had — refuse if run ON kwanz-ws:
#      forwarding the VM to itself is at best a no-op). It is backgrounded
#      here so the script can continue, and is torn down automatically when
#      the console exits (Ctrl-C).
#   4. The console runs the profile's standard local dev loop:
#      `cd incident-console && uv run streamlit run app.py` (see
#      incident-console/README.md). It occupies the foreground; Ctrl-C when
#      you're done.
#
# Overrides (defaults below are the shared-VM values from the old
# deploy/dotfiles/aliases.sh):
#   VSS_SSH_TARGET           full "user@host" SSH login for the VM. If set,
#                            used as-is with no prompt. If unset, the VM
#                            username is resolved by resolve-ssh-target.sh:
#                            VSS_SSH_USER env var (non-interactive override),
#                            else an interactive prompt pre-filled with
#                            $USER/whoami (Enter accepts it), else $USER/
#                            whoami silently when not running in a terminal.
#                            VSS_SSH_HOST (default: kwanz-ws) sets the host.
#   VSS_SSH_USER             VM username override (see VSS_SSH_TARGET above)
#   VSS_SSH_HOST             VM hostname (default: kwanz-ws)
#   VSS_VM_IP                VM address for the tunnel forwards (default: 10.131.1.5)
#   VSS_REPO_ROOT            the VM's shared checkout (default: /srv/rise-up/vss)
#   INCIDENT_EXPECTED_CONTAINERS   space-separated list of backend services
#                            start.sh expects to be up for a "full" deploy
#                            (default: the MVP1 backend set from
#                            dev-profile-incident/README.md's "What's
#                            actually running" table; adjust if the
#                            hosted-model switch changes the service set —
#                            the VM console container and knowingly-not-
#                            running services are intentionally excluded)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=resolve-ssh-target.sh
source "${SCRIPT_DIR}/resolve-ssh-target.sh"
VSS_VM_IP="${VSS_VM_IP:-10.131.1.5}"
VSS_REPO_ROOT="${VSS_REPO_ROOT:-/srv/rise-up/vss}"
INCIDENT_EXPECTED_CONTAINERS="${INCIDENT_EXPECTED_CONTAINERS:-vss-agent vss-vios-streamprocessing vss-vios-nvstreamer vss-vios-ingress vss-haproxy-ingress vss-vios-postgres redis phoenix}"

# Laptop-side only: refuse to run ON kwanz-ws (same guard as the old
# mdx-tunnel-incident alias).
if [ "$(hostname -s 2>/dev/null)" = "kwanz-ws" ]; then
  echo "start.sh: run this from your laptop, not on kwanz-ws (it SSHes to the VM, forwards laptop ports to it, and runs the console locally)." >&2
  exit 1
fi

TUNNEL_PID=""
cleanup() {
  if [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    echo "start.sh: closed the backgrounded SSH tunnel (pid $TUNNEL_PID)."
    TUNNEL_PID=""
  fi
}
trap cleanup EXIT INT TERM

echo "=== STEP 1/3 — Checking backend deploy state on $VSS_SSH_TARGET (project: mdx) ==="

state_output="$(ssh -o ConnectTimeout=10 "$VSS_SSH_TARGET" \
  "cd '$VSS_REPO_ROOT/deploy/docker' && docker compose -p mdx ps -a --format '{{.Name}} {{.State}}'" 2>&1)"
ssh_rc=$?
if [ "$ssh_rc" -ne 0 ]; then
  echo "start.sh: could not query deploy state over SSH ($VSS_SSH_TARGET)." >&2
  echo "${state_output}" >&2
  echo "  Is the VM reachable (tailscale/network) and is docker compose available?" >&2
  exit 1
fi

echo "--- compose project 'mdx' on the VM ---"
if [ -z "$state_output" ]; then
  echo "(no containers)"
else
  echo "${state_output}"
fi

up_named=()
missing=()
for svc in ${INCIDENT_EXPECTED_CONTAINERS}; do
  # Match both name shapes this VM has produced: compose-default names
  # prefixed by the project ("mdx-vss-agent-1") and explicit container_name
  # overrides with no prefix ("vss-agent"). A service is "up" only if its
  # name token is followed by the running state; "-ui"/"-postgres"-style
  # suffixes and 'restarting'/'exited'/'created' must NOT count.
  if echo "${state_output}" | grep -Eq "(^|[[:space:]-])${svc}(-[0-9]+)?[[:space:]]+running[[:space:]]*$"; then
    up_named+=("${svc}")
  else
    missing+=("${svc}")
  fi
done

echo "--- expected backend containers ---"
echo "  expected: ${INCIDENT_EXPECTED_CONTAINERS}"
if [ "${#up_named[@]}" -gt 0 ]; then
  echo "  up:       ${up_named[*]}"
else
  echo "  up:       (none)"
fi
if [ "${#missing[@]}" -gt 0 ]; then
  echo "  missing:  ${missing[*]}"
fi

if [ "${#missing[@]}" -eq 0 ]; then
  echo "start.sh: all expected backend containers are already running — skipping the backend deploy."
elif [ "${#up_named[@]}" -eq 0 ]; then
  echo "start.sh: nothing relevant is running — deploying the backend fresh."
  echo "=== STEP 2/3 — Deploying backend (hosted-model config via generated.env.remote) ==="

  deploy_script=$(cat <<EOF
set -e
cd "$VSS_REPO_ROOT/deploy/docker"
if [ ! -f developer-profiles/dev-profile-incident/generated.env.remote ]; then
  echo "start.sh: developer-profiles/dev-profile-incident/generated.env.remote not found on the VM." >&2
  echo "  Create it from the tracked .env template and fill in the real values:" >&2
  echo "  cp ${VSS_REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/.env ${VSS_REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote" >&2
  echo "  (see docs/incident-plan/incident-plan-implementation-remote.md §2)" >&2
  exit 1
fi
if sudo -n true 2>/dev/null; then
  sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d
else
  docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d
fi
EOF
)
  echo "--- deploying over SSH (this can take a while: image pulls, model/config setup) ---"
  echo "--- command: cd $VSS_REPO_ROOT/deploy/docker && docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d ---"
  ssh "$VSS_SSH_TARGET" "bash -s" <<<"${deploy_script}"
  deploy_rc=$?
  if [ "$deploy_rc" -ne 0 ]; then
    echo "start.sh: backend deploy over SSH failed (exit $deploy_rc)." >&2
    echo "  Check the output above, fix the VM state, and re-run ./start.sh." >&2
    exit 1
  fi
  echo "start.sh: backend deploy completed."
else
  echo "start.sh: PARTIAL deploy detected on ${VSS_SSH_TARGET} — stopping." >&2
  echo "  Running too much/little state to trust a redeploy; start.sh deliberately" >&2
  echo "  never auto-reconciles or force-redeploys over a partial state." >&2
  echo "  Up:       ${up_named[*]:-none}" >&2
  echo "  Missing:  ${missing[*]}" >&2
  echo "  Expected: ${INCIDENT_EXPECTED_CONTAINERS}" >&2
  echo "  Clear the partial state manually (on kwanz-ws: down.sh, or plain 'docker compose -p mdx down' — never '-v'), then re-run ./start.sh." >&2
  exit 1
fi

echo "=== NEXT STEP — Opening the SSH tunnel (laptop-side, backgrounded) ==="
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -L 8000:"$VSS_VM_IP":8000 \
  -L 30081:"$VSS_VM_IP":30081 \
  -L 30082:"$VSS_VM_IP":30082 \
  -L 7777:"$VSS_VM_IP":7777 \
  "$VSS_SSH_TARGET" &
TUNNEL_PID=$!

echo "  tunnel pid $TUNNEL_PID; waiting for the tunneled agent health check (localhost:8000/health)..."
tunnel_ok=""
for _i in $(seq 1 30); do
  if curl -sf --max-time 5 http://localhost:8000/health | grep -q isAlive; then
    tunnel_ok=1
    break
  fi
  sleep 2
done
if [ -z "$tunnel_ok" ]; then
  echo "start.sh: the tunneled agent never came up on localhost:8000." >&2
  echo "  Run ./tunnel-check.sh for a per-port breakdown." >&2
  cleanup
  exit 1
fi
echo "  agent ok (localhost:8000 -> ${VSS_VM_IP}:8000)"

echo "=== FINAL STEP — Starting the local incident-console ==="
if ! command -v uv >/dev/null 2>&1; then
  echo "start.sh: 'uv' not found on PATH. Install uv first (see incident-console/README.md's local dev loop), then re-run." >&2
  cleanup
  exit 1
fi
cd "${SCRIPT_DIR}/incident-console"
uv sync

echo "  Streamlit running at http://localhost:8501 — Ctrl-C here (or close this terminal) stops the console and closes the tunnel."
uv run streamlit run app.py
console_rc=$?
cleanup
exit "$console_rc"
