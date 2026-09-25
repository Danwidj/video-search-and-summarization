#!/usr/bin/env bash
#
# start.sh — the one-command daily entry point for the incident-console
# workflow. RUN FROM YOUR LAPTOP:
#
#   cd deploy/docker/developer-profiles/dev-profile-incident && ./start.sh
#
# Modes (via --mode or VSS_START_MODE, default: vm):
#   vm    — real VM agent (checks/deploys kwanz-ws over SSH, opens the SSH
#           tunnel). Exports ANALYSIS_MODE=agent so v2 calls the agent's
#           /analyze endpoint directly. No local vlm-gateway.
#   local — fully local, no VM/SSH. Starts mock-backend (127.0.0.1:7777)
#           and vlm-gateway (127.0.0.1:8600) locally. Exports
#           ANALYSIS_MODE=gateway so v2 calls the local gateway.
#
# Both modes launch incident-console-v2 (Next.js, port 3200). The Streamlit
# v1 console is no longer started by this script — see local-start.sh or
# incident-console/README.md if you need it.
#
# Architecture (Native vs Docker Split):
#   - DOCKER SERVICES: Foundational appliance containers (VIOS/VST, HAProxy,
#     Postgres, Redis, Phoenix, and optional Kafka/ElasticSearch).
#   - NATIVE SERVICES: Fast-iterating application modules running directly
#     on kwanz-ws (vss-agent via NAT framework, plus optional analytics
#     video-analytics-api and behavior-analytics).
#
# Execution flow (vm mode):
#   1. Checks the current deploy state over SSH against the VM:
#        - Docker containers via `docker compose -p mdx ps`
#        - Native services via `native-services.sh status`
#   2. Branches on that state:
#        - NOTHING expected running  -> deploy the backend fresh over SSH:
#          Starts Docker appliances (`docker compose ... up -d <docker-services>`),
#          then starts native services via `native-services.sh start`.
#          Then opens the tunnel and starts v2.
#        - EVERYTHING expected up    -> skip the deploy, straight to
#          tunnel + v2.
#        - PARTIAL (some up)         -> SELF-HEAL. Prints what's missing,
#          starts only the missing Docker and native services over SSH,
#          then proceeds to the tunnel.
#   3. The tunnel step is laptop-side only (same hostname guard the old
#      `mdx-tunnel-incident` alias had — refuse if run ON kwanz-ws:
#      forwarding the VM to itself is at best a no-op). It is backgrounded
#      here so the script can continue, and is torn down automatically when
#      the console exits (Ctrl-C).
#   4. v2 runs the profile's standard local dev loop:
#      `cd incident-console-v2 && npm run dev -- --port 3200` (see
#      incident-console-v2/README.md). It occupies the foreground; Ctrl-C when
#      you're done.
#
# Overrides:
#   VSS_START_MODE           'vm' or 'local'. Default: 'vm'. In 'local' mode,
#                            SSH is never resolved or touched.
#   VSS_SSH_TARGET           full "user@host" SSH login for the VM. If set,
#                            used as-is. If unset, the VM username is
#                            resolved non-interactively by resolve-ssh-target.sh:
#                            VSS_SSH_USER env var, else ~/.ssh/config User,
#                            else $USER/whoami. No prompt is ever shown.
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

# Parse --mode flag
VSS_START_MODE="${VSS_START_MODE:-vm}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      VSS_START_MODE="${2:-}"
      shift 2
      ;;
    --mode=*)
      VSS_START_MODE="${1#*=}"
      shift
      ;;
    *)
      echo "start.sh: unknown argument '$1'" >&2
      echo "Usage: ./start.sh [--mode local|vm]" >&2
      exit 1
      ;;
  esac
done

case "$VSS_START_MODE" in
  vm|local) ;;
  *)
    echo "start.sh: VSS_START_MODE must be 'vm' or 'local' (got '$VSS_START_MODE')." >&2
    exit 1
    ;;
esac

# Laptop-side only: refuse to run ON kwanz-ws
if [ "$(hostname -s 2>/dev/null)" = "kwanz-ws" ]; then
  echo "start.sh: run this from your laptop, not on kwanz-ws (it SSHes to the VM, forwards laptop ports to it, and runs v2 locally)." >&2
  exit 1
fi

TUNNEL_PID=""
MOCK_BACKEND_PID=""
VLM_GATEWAY_PID=""

cleanup() {
  if [ -n "$VLM_GATEWAY_PID" ] && kill -0 "$VLM_GATEWAY_PID" 2>/dev/null; then
    kill "$VLM_GATEWAY_PID" 2>/dev/null || true
    echo "start.sh: stopped the local vlm-gateway (pid $VLM_GATEWAY_PID)."
    VLM_GATEWAY_PID=""
  fi
  if [ -n "$MOCK_BACKEND_PID" ] && kill -0 "$MOCK_BACKEND_PID" 2>/dev/null; then
    kill "$MOCK_BACKEND_PID" 2>/dev/null || true
    echo "start.sh: stopped the local mock backend (pid $MOCK_BACKEND_PID)."
    MOCK_BACKEND_PID=""
  fi
  if [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    echo "start.sh: closed the backgrounded SSH tunnel (pid $TUNNEL_PID)."
    TUNNEL_PID=""
  fi
}
trap cleanup EXIT INT TERM

if [ "$VSS_START_MODE" = "vm" ]; then
  # shellcheck source=.scripts/resolve-ssh-target.sh
  source "${SCRIPT_DIR}/.scripts/resolve-ssh-target.sh"
  VSS_VM_IP="${VSS_VM_IP:-10.131.1.5}"
  VSS_REPO_ROOT="${VSS_REPO_ROOT:-/srv/rise-up/vss}"
  ENABLE_ANALYTICS="${ENABLE_ANALYTICS:-false}"

  # Base Docker infrastructure (appliances)
  default_docker_services="vss-vios-streamprocessing vss-vios-nvstreamer vss-vios-ingress vss-haproxy-ingress vss-vios-postgres redis phoenix kafka"
  if [ "${ENABLE_ANALYTICS}" = "true" ]; then
    default_docker_services="${default_docker_services} elasticsearch"
  fi
  INCIDENT_DOCKER_SERVICES="${INCIDENT_DOCKER_SERVICES:-${INCIDENT_EXPECTED_CONTAINERS:-$default_docker_services}}"

  # Native VM services
  default_native_services="vss-agent"
  if [ "${ENABLE_ANALYTICS}" = "true" ]; then
    default_native_services="${default_native_services} video-analytics-api behavior-analytics"
  fi
  INCIDENT_NATIVE_SERVICES="${INCIDENT_NATIVE_SERVICES:-$default_native_services}"

  # Fast SSH preflight check before any tunnel, deploy check, env generation, npm install, or UI start
  if ! preflight_err="$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$VSS_SSH_TARGET" true 2>&1)"; then
    echo "start.sh: SSH connection to '$VSS_SSH_TARGET' failed." >&2
    if [ -n "$preflight_err" ]; then
      echo "  SSH error: ${preflight_err}" >&2
    fi
    echo "  Fix: Check your 'Host kwanz-ws' entry in ~/.ssh/config and ensure Tailscale/network is connected." >&2
    exit 1
  fi

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
    "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh' status --porcelain" 2>&1)"
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
    "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh' status" 2>&1 || true

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
  echo "  (see .docs/incident-profile-operations.md §5)" >&2
  exit 1
fi

map_docker_service() {
  case "\$1" in
    vss-vios-streamprocessing) echo "streamprocessing-ms" ;;
    vss-vios-nvstreamer)       echo "nvstreamer-2d-fusion" ;;
    vss-vios-ingress)          echo "vst-ingress" ;;
    vss-vios-postgres)         echo "centralizedb" ;;
    *)                         echo "\$1" ;;
  esac
}

COMPOSE_SERVICES=""
for svc in ${INCIDENT_DOCKER_SERVICES}; do
  mapped="\$(map_docker_service "\$svc")"
  COMPOSE_SERVICES="\${COMPOSE_SERVICES} \${mapped}"
done
COMPOSE_SERVICES="\${COMPOSE_SERVICES# }"

echo "--- starting Docker appliance containers (\${COMPOSE_SERVICES}) ---"
if sudo -n true 2>/dev/null; then
  sudo docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d --scale init-dirs=0 --scale render-config=0 --scale wdm-env-from-config=0 --scale sdr-controller=0 \${COMPOSE_SERVICES}
else
  docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d --scale init-dirs=0 --scale render-config=0 --scale wdm-env-from-config=0 --scale sdr-controller=0 \${COMPOSE_SERVICES}
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
      "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh' start ${INCIDENT_NATIVE_SERVICES}"
    native_start_rc=$?
    if [ "$native_start_rc" -ne 0 ]; then
      echo "start.sh: Native service startup over SSH failed (exit $native_start_rc)." >&2
      exit 1
    fi

    echo "start.sh: backend deploy completed (Docker appliances + Native services)."
  else
    echo "start.sh: partial deploy detected — starting missing services..."
    if [ "${#docker_missing[@]}" -gt 0 ]; then
      echo "--- starting missing Docker appliances (${docker_missing[*]}) over SSH ---"
      deploy_missing_script=$(cat <<EOF
set -e
cd "$VSS_REPO_ROOT/deploy/docker"
if [ ! -f developer-profiles/dev-profile-incident/generated.env.remote ]; then
  echo "start.sh: developer-profiles/dev-profile-incident/generated.env.remote not found on the VM." >&2
  exit 1
fi

map_docker_service() {
  case "\$1" in
    vss-vios-streamprocessing) echo "streamprocessing-ms" ;;
    vss-vios-nvstreamer)       echo "nvstreamer-2d-fusion" ;;
    vss-vios-ingress)          echo "vst-ingress" ;;
    vss-vios-postgres)         echo "centralizedb" ;;
    *)                         echo "\$1" ;;
  esac
}

COMPOSE_SERVICES=""
for svc in ${docker_missing[*]}; do
  mapped="\$(map_docker_service "\$svc")"
  COMPOSE_SERVICES="\${COMPOSE_SERVICES} \${mapped}"
done
COMPOSE_SERVICES="\${COMPOSE_SERVICES# }"

echo "--- starting Docker appliance containers (\${COMPOSE_SERVICES}) ---"
if sudo -n true 2>/dev/null; then
  sudo docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d --scale init-dirs=0 --scale render-config=0 --scale wdm-env-from-config=0 --scale sdr-controller=0 \${COMPOSE_SERVICES}
else
  docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d --scale init-dirs=0 --scale render-config=0 --scale wdm-env-from-config=0 --scale sdr-controller=0 \${COMPOSE_SERVICES}
fi
EOF
)
      ssh "$VSS_SSH_TARGET" "bash -s" <<<"${deploy_missing_script}"
      deploy_rc=$?
      if [ "$deploy_rc" -ne 0 ]; then
        echo "start.sh: missing Docker appliance deploy over SSH failed (exit $deploy_rc)." >&2
        exit 1
      fi
    fi

    if [ "${#native_missing[@]}" -gt 0 ]; then
      echo "--- starting missing Native services (${native_missing[*]}) over SSH ---"
      ssh "$VSS_SSH_TARGET" \
        "bash '$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh' start ${native_missing[*]}"
      native_start_rc=$?
      if [ "$native_start_rc" -ne 0 ]; then
        echo "start.sh: missing Native service startup over SSH failed (exit $native_start_rc)." >&2
        exit 1
      fi
    fi

    echo "start.sh: missing services started successfully."
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

  export INCIDENT_AGENT_BASE_URL="http://localhost:8000"
  export ANALYSIS_MODE="agent"
elif [ "$VSS_START_MODE" = "local" ]; then
  echo "=== Starting local mock backend (mock-backend/base_profile_mock, :7777) ==="
  (
    cd "${SCRIPT_DIR}/mock-backend/base_profile_mock"
    uv sync
    exec uv run --env-file "${SCRIPT_DIR}/incident-console/.env.local" \
      uvicorn base_profile_mock.app:create_app --factory --host 127.0.0.1 --port 7777
  ) &
  MOCK_BACKEND_PID=$!

  echo "=== Starting local vlm-gateway (:8600) ==="
  (
    cd "${SCRIPT_DIR}/vlm-gateway"
    uv sync
    exec uv run --env-file "${SCRIPT_DIR}/vlm-gateway/.env.local" \
      uvicorn app:app --host 127.0.0.1 --port 8600
  ) &
  VLM_GATEWAY_PID=$!

  # Give services a moment to start
  sleep 2

  export INCIDENT_AGENT_BASE_URL="http://127.0.0.1:7777"
  export VLM_GATEWAY_URL="http://127.0.0.1:8600"
  export ANALYSIS_MODE="gateway"
fi

echo "  INCIDENT_AGENT_BASE_URL=${INCIDENT_AGENT_BASE_URL}"
if [ -n "${VLM_GATEWAY_URL:-}" ]; then
  echo "  VLM_GATEWAY_URL=${VLM_GATEWAY_URL}"
fi
echo "  ANALYSIS_MODE=${ANALYSIS_MODE}"

echo "=== FINAL STEP — Starting incident-console-v2 ==="
if ! command -v npm >/dev/null 2>&1; then
  echo "start.sh: 'npm' not found on PATH. Install Node.js/npm first, then re-run." >&2
  exit 1
fi
cd "${SCRIPT_DIR}/incident-console-v2"
npm install

echo "  v2 running at http://localhost:3200 — Ctrl-C here (or close this terminal) stops v2 and any backgrounded local services/tunnel."
npm run dev -- --port 3200
console_rc=$?
cleanup
exit "$console_rc"