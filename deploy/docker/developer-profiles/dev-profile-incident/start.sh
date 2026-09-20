#!/usr/bin/env bash
#
# start.sh — the one-command daily entry point for the incident-console
# workflow. RUN FROM YOUR LAPTOP:
#
#   cd deploy/docker/developer-profiles/dev-profile-incident && ./start.sh
#
# Architecture (Native vs Docker Split):
#   - DOCKER SERVICES: Foundational appliance containers (VIOS/VST, HAProxy,
#     Postgres, Redis, Phoenix, and optional Kafka/ElasticSearch).
#   - NATIVE SERVICES: Fast-iterating application modules running directly
#     on kwanz-ws (vss-agent via NAT framework, plus optional analytics
#     video-analytics-api and behavior-analytics).
#
# Execution flow:
#   1. Checks the current deploy state over SSH against the VM:
#        - Docker containers via `docker compose -p mdx ps`
#        - Native services via `native-services.sh status`
#   2. Branches on that state:
#        - NOTHING expected running  -> deploy the backend fresh over SSH:
#          Starts Docker appliances (`docker compose ... up -d <docker-services>`),
#          then starts native services via `native-services.sh start`.
#          Then opens the tunnel and starts the local console.
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
# Overrides:
#   VSS_SSH_TARGET           full "user@host" SSH login for the VM. If set,
#                            used as-is with no prompt. If unset, the VM
#                            username is resolved by resolve-ssh-target.sh:
#                            VSS_SSH_USER env var (non-interactive override),
#                            else ~/.ssh/config User, else $USER/whoami.
#                            VSS_SSH_HOST (default: kwanz-ws) sets the host.
#   VSS_SSH_USER             VM username override (see VSS_SSH_TARGET above)
#   VSS_SSH_HOST             VM hostname (default: kwanz-ws)
#   VSS_VM_IP                VM address for the tunnel forwards (default: 10.131.1.5)
#   VSS_REPO_ROOT            the VM's shared checkout (default: /srv/rise-up/vss)
#   ENABLE_ANALYTICS         set to 'true' to include video-analytics-api and
#                            behavior-analytics natively, plus elasticsearch/kafka in Docker
#   INCIDENT_DOCKER_SERVICES space-separated list of Docker services to expect/run
#   INCIDENT_NATIVE_SERVICES space-separated list of native VM services to expect/run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=scripts/resolve-ssh-target.sh
source "${SCRIPT_DIR}/scripts/resolve-ssh-target.sh"
VSS_VM_IP="${VSS_VM_IP:-10.131.1.5}"
VSS_REPO_ROOT="${VSS_REPO_ROOT:-/srv/rise-up/vss}"
ENABLE_ANALYTICS="${ENABLE_ANALYTICS:-false}"

# Base Docker infrastructure (appliances)
default_docker_services="vss-vios-streamprocessing vss-vios-nvstreamer vss-vios-ingress vss-haproxy-ingress vss-vios-postgres redis phoenix"
if [ "${ENABLE_ANALYTICS}" = "true" ]; then
  default_docker_services="${default_docker_services} elasticsearch kafka"
fi
INCIDENT_DOCKER_SERVICES="${INCIDENT_DOCKER_SERVICES:-${INCIDENT_EXPECTED_CONTAINERS:-$default_docker_services}}"

# Native VM services
default_native_services="vss-agent"
if [ "${ENABLE_ANALYTICS}" = "true" ]; then
  default_native_services="${default_native_services} video-analytics-api behavior-analytics"
fi
INCIDENT_NATIVE_SERVICES="${INCIDENT_NATIVE_SERVICES:-$default_native_services}"

# Laptop-side only: refuse to run ON kwanz-ws
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

echo "=== STEP 1/3 — Checking backend deploy state on $VSS_SSH_TARGET ==="

# 1. Query Docker containers state
state_output="$(ssh -o ConnectTimeout=10 "$VSS_SSH_TARGET" \
  "cd '$VSS_REPO_ROOT/deploy/docker' && docker compose -p mdx ps -a --format '{{.Name}} {{.State}}'" 2>&1)"
ssh_rc=$?
if [ "$ssh_rc" -ne 0 ]; then
  echo "start.sh: could not query Docker deploy state over SSH ($VSS_SSH_TARGET)." >&2
  echo "${state_output}" >&2
  echo "  Is the VM reachable (tailscale/network) and is docker compose available?" >&2
  exit 1
fi

# 2. Query Native services state
native_output="$(ssh -o ConnectTimeout=10 "$VSS_SSH_TARGET" \
  "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/scripts/native-services.sh' status --porcelain" 2>&1)"
native_rc=$?
if [ "$native_rc" -ne 0 ]; then
  echo "start.sh: could not query native services state over SSH ($VSS_SSH_TARGET)." >&2
  echo "${native_output}" >&2
  exit 1
fi

echo "--- Docker containers (project: mdx) ---"
if [ -z "$state_output" ]; then
  echo "(no containers)"
else
  echo "${state_output}"
fi

echo "--- Native services (managed natively) ---"
ssh "$VSS_SSH_TARGET" \
  "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/scripts/native-services.sh' status" 2>&1 || true

docker_up=()
docker_missing=()
for svc in ${INCIDENT_DOCKER_SERVICES}; do
  if echo "${state_output}" | grep -Eq "(^|[[:space:]-])${svc}(-[0-9]+)?[[:space:]]+running[[:space:]]*$"; then
    docker_up+=("${svc}")
  else
    docker_missing+=("${svc}")
  fi
done

native_up=()
native_missing=()
for svc in ${INCIDENT_NATIVE_SERVICES}; do
  if echo "${native_output}" | grep -Eq "^${svc}:running:"; then
    native_up+=("${svc}")
  else
    native_missing+=("${svc}")
  fi
done

echo "--- Backend status evaluation ---"
echo "  Docker services expected: ${INCIDENT_DOCKER_SERVICES}"
echo "    up:      ${docker_up[*]:-(none)}"
if [ "${#docker_missing[@]}" -gt 0 ]; then
  echo "    missing: ${docker_missing[*]}"
fi

echo "  Native services expected: ${INCIDENT_NATIVE_SERVICES}"
echo "    up:      ${native_up[*]:-(none)}"
if [ "${#native_missing[@]}" -gt 0 ]; then
  echo "    missing: ${native_missing[*]}"
fi

total_up_count=$((${#docker_up[@]} + ${#native_up[@]}))
total_missing_count=$((${#docker_missing[@]} + ${#native_missing[@]}))

if [ "$total_missing_count" -eq 0 ]; then
  echo "start.sh: all expected backend services (Docker and native) are already running — skipping backend deploy."
elif [ "$total_up_count" -eq 0 ]; then
  echo "start.sh: nothing relevant is running — deploying the backend fresh."
  echo "=== STEP 2/3 — Deploying backend (Docker appliances + Native services) ==="

  deploy_script=$(cat <<EOF
set -e
cd "$VSS_REPO_ROOT/deploy/docker"
if [ ! -f developer-profiles/dev-profile-incident/generated.env.remote ]; then
  echo "start.sh: developer-profiles/dev-profile-incident/generated.env.remote not found on the VM." >&2
  echo "  Create it from the tracked .env template and fill in the real values:" >&2
  echo "  cp ${VSS_REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/.env ${VSS_REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote" >&2
  echo "  (see incident-plan/incident-plan-implementation-remote.md §2)" >&2
  exit 1
fi
echo "--- starting Docker appliance containers (${INCIDENT_DOCKER_SERVICES}) ---"
if sudo -n true 2>/dev/null; then
  sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d ${INCIDENT_DOCKER_SERVICES}
else
  docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d ${INCIDENT_DOCKER_SERVICES}
fi
EOF
)
  echo "--- deploying Docker appliances over SSH ---"
  ssh "$VSS_SSH_TARGET" "bash -s" <<<"${deploy_script}"
  deploy_rc=$?
  if [ "$deploy_rc" -ne 0 ]; then
    echo "start.sh: Docker appliance deploy over SSH failed (exit $deploy_rc)." >&2
    exit 1
  fi

  echo "--- starting Native services over SSH (${INCIDENT_NATIVE_SERVICES}) ---"
  ssh "$VSS_SSH_TARGET" \
    "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/scripts/native-services.sh' start ${INCIDENT_NATIVE_SERVICES}"
  native_start_rc=$?
  if [ "$native_start_rc" -ne 0 ]; then
    echo "start.sh: Native service startup over SSH failed (exit $native_start_rc)." >&2
    exit 1
  fi

  echo "start.sh: backend deploy completed (Docker appliances + Native services)."
else
  echo "start.sh: PARTIAL deploy detected on ${VSS_SSH_TARGET} — stopping." >&2
  echo "  Running too much/little state to trust a redeploy; start.sh deliberately" >&2
  echo "  never auto-reconciles or force-redeploys over a partial state." >&2
  echo "  Docker up:       ${docker_up[*]:-none}" >&2
  echo "  Docker missing:  ${docker_missing[*]:-none}" >&2
  echo "  Native up:       ${native_up[*]:-none}" >&2
  echo "  Native missing:  ${native_missing[*]:-none}" >&2
  echo "  Clear the partial state manually (on kwanz-ws: run down.sh to stop Docker and native services), then re-run ./start.sh." >&2
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
