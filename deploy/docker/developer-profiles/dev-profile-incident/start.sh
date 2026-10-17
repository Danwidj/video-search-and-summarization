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
#           /analyze endpoint directly. No local vlm-gateway. The search route
#           (POST /api/v1/incidents/search) is always mounted on vss-agent (:8000)
#           with an always-on VLM critic and persisted ranking/verdicts.
#   local — fully local, no VM/SSH. Starts mock-backend (127.0.0.1:7777)
#           and vlm-gateway (127.0.0.1:8600) locally. Exports
#           ANALYSIS_MODE=gateway so v2 calls the local gateway. The search route
#           (POST /api/v1/incidents/search) is always mounted on mock-backend (:7777).
#
# Both modes start and mount the search route automatically with NO opt-in
# --search flag (search is always on).
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
#   0. Preflight: probes SSH and, on failure, says why (Tailscale not
#      installed/stopped/logged out, VM offline in the tailnet, host not
#      resolving, SSH timeout/refused, no route, auth, host key) and what to
#      do (.scripts/vm-preflight.sh). Then detects the VM address.
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
#      Starting Docker services runs .scripts/vm-ensure-docker.sh on the VM
#      (piped over SSH): it clones the repo if the checkout is missing, fixes a
#      stale HOST_IP in generated.env.remote (backed up first), pulls missing
#      images, then runs `docker compose up -d` under a timeout. Every step is
#      bounded and fails with a message instead of hanging.
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
#   VSS_VM_IP                VM address for the tunnel forwards. If unset, detected
#                            from the VM over SSH (its default-route source address),
#                            falling back to 10.131.1.5 if detection fails.
#   VSS_REPO_ROOT            the VM's shared checkout (default: /srv/rise-up/vss)
#   VSS_REPO_URL             git URL to clone if the VM has no checkout (default: this
#                            clone's `origin`)
#   VSS_SSH_CONNECT_TIMEOUT  SSH connect timeout in seconds (default: 10)
#   VSS_PULL_TIMEOUT         image pull/clone timeout on the VM, seconds (default: 1800)
#   VSS_COMPOSE_UP_TIMEOUT   `docker compose up` timeout on the VM, seconds (default: 600)
#   VSS_NATIVE_START_TIMEOUT native service start timeout on the VM, seconds (default: 300)
#   --no-console             bring the backend and tunnel up, skip incident-console-v2,
#                            and hold the tunnel open (for checking the VM side only)
#   ENABLE_ANALYTICS         set to 'true' to include video-analytics-api and
#                            behavior-analytics natively, plus elasticsearch/kafka in Docker
#   INCIDENT_DOCKER_SERVICES space-separated list of Docker services to expect/run
#   INCIDENT_NATIVE_SERVICES space-separated list of native VM services to expect/run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse --mode / --no-console flags (--no-console: bring the backend and tunnel up, skip the Next.js console)
NO_CONSOLE=0
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
    --no-console)
      NO_CONSOLE=1
      shift
      ;;
    *)
      echo "start.sh: unknown argument '$1'" >&2
      echo "Usage: ./start.sh [--mode local|vm] [--no-console]" >&2
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
TUNNEL_LOG=""
MOCK_BACKEND_PID=""
VLM_GATEWAY_PID=""

# Laptop-side name -> compose service name for the Docker appliances.
map_docker_service() {
  case "$1" in
    vss-vios-streamprocessing) echo "streamprocessing-ms" ;;
    vss-vios-nvstreamer)       echo "nvstreamer-2d-fusion" ;;
    vss-vios-ingress)          echo "vst-ingress" ;;
    vss-vios-postgres)         echo "centralizedb" ;;
    *)                         echo "$1" ;;
  esac
}

cleanup() {
  if [ -n "${VM_SSH_PID:-}" ] && kill -0 "$VM_SSH_PID" 2>/dev/null; then
    kill "$VM_SSH_PID" 2>/dev/null || true
    VM_SSH_PID=""
  fi
  [ -n "$TUNNEL_LOG" ] && rm -f "$TUNNEL_LOG"
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

  # shellcheck source=.scripts/vm-preflight.sh
  source "${SCRIPT_DIR}/.scripts/vm-preflight.sh"

  # Case 1 (VM unreachable): classify why and say what to do, before anything else runs.
  if ! vm_preflight_ssh; then
    exit 1
  fi
  VSS_VM_IP="$(vm_detect_ip)"

  VSS_PULL_TIMEOUT="${VSS_PULL_TIMEOUT:-1800}"
  VSS_COMPOSE_UP_TIMEOUT="${VSS_COMPOSE_UP_TIMEOUT:-600}"
  VSS_NATIVE_START_TIMEOUT="${VSS_NATIVE_START_TIMEOUT:-300}"
  VSS_REPO_URL="${VSS_REPO_URL:-$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true)}"
  vm_profile_dir="$VSS_REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident"

  echo "=== STEP 1/3 — Checking backend deploy state on $VSS_SSH_TARGET ==="

  state_output=""
  native_output=""
  # The ssh commands below deliberately expand the paths on the client side.
  # shellcheck disable=SC2029
  if ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" "test -f '$VSS_REPO_ROOT/deploy/docker/compose.yml'" 2>/dev/null; then
    # A failing query is not fatal: the services count as missing and the deploy step
    # below diagnoses why (docker down, user not in the docker group, ...).
    # shellcheck disable=SC2029
    if ! state_output="$(ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" \
      "cd '$VSS_REPO_ROOT/deploy/docker' && timeout 60 docker compose -p mdx ps -a --format '{{.Name}} {{.State}}'" 2>&1)"; then
      echo "start.sh: could not list the VM's Docker containers (${state_output:-no output}); treating them as not running." >&2
      state_output=""
    fi
    # shellcheck disable=SC2029
    if ! native_output="$(ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" \
      "timeout 60 bash '$vm_profile_dir/.scripts/native-services.sh' status --porcelain" 2>&1)"; then
      echo "start.sh: could not read the VM's native service status (${native_output:-no output})." >&2
      echo "  If native-services.sh is missing, the VM checkout is behind: run 'git pull' in $VSS_REPO_ROOT." >&2
      native_output=""
    fi
  else
    echo "start.sh: no VSS checkout at $VSS_REPO_ROOT on the VM; it will be cloned in the deploy step."
  fi

  echo "--- Docker containers (project: mdx) ---"
  if [ -z "$state_output" ]; then
    echo "(no containers)"
  else
    echo "${state_output}"
  fi

  echo "--- Native services (managed natively) ---"
  # shellcheck disable=SC2029
  ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" \
    "timeout 60 bash '$vm_profile_dir/.scripts/native-services.sh' status" 2>&1 || true

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
  else
    if [ "$total_up_count" -eq 0 ]; then
      echo "start.sh: nothing relevant is running — deploying the backend fresh."
    else
      echo "start.sh: partial deploy detected — starting missing services..."
    fi
    echo "=== STEP 2/3 — Starting missing backend services (Docker appliances + Native services) ==="

    # Cases 2 and 3 (services stopped, repo/images not downloaded): vm-ensure-docker.sh
    # runs on the VM and clones/pulls what is missing, then runs a bounded `compose up`.
    if [ "${#docker_missing[@]}" -gt 0 ]; then
      compose_services=()
      for svc in "${docker_missing[@]}"; do
        compose_services+=("$(map_docker_service "$svc")")
      done
      echo "--- starting missing Docker appliances (${docker_missing[*]}) over SSH ---"
      docker_rc=0
      # ssh joins its arguments into one string, so quote them (an empty repo URL must survive).
      remote_cmd="bash -s -- $(printf '%q ' "$VSS_REPO_ROOT" "$VSS_REPO_URL" "$VSS_PULL_TIMEOUT" "$VSS_COMPOSE_UP_TIMEOUT" "${compose_services[@]}")"
      vm_ssh_limited $((VSS_PULL_TIMEOUT + VSS_COMPOSE_UP_TIMEOUT + 300)) "$VSS_SSH_TARGET" "$remote_cmd" \
        < "${SCRIPT_DIR}/.scripts/vm-ensure-docker.sh" || docker_rc=$?
      if [ "$docker_rc" -ne 0 ]; then
        case "$docker_rc" in
          124)     echo "start.sh: the Docker step on the VM timed out; a health check is stuck (see the [vm] lines above). Raise VSS_COMPOSE_UP_TIMEOUT only if the services are genuinely just slow." >&2 ;;
          143|137) echo "start.sh: gave up waiting for the VM's Docker step (connection lost or no reply). Re-run; nothing was left half-configured." >&2 ;;
          255)     echo "start.sh: the SSH connection to the VM dropped during the Docker step. Re-run start.sh." >&2 ;;
          *)       echo "start.sh: the Docker step on the VM failed (exit $docker_rc); see the [vm] lines above." >&2 ;;
        esac
        exit 1
      fi
    fi

    if [ "${#native_missing[@]}" -gt 0 ]; then
      echo "--- starting missing Native services (${native_missing[*]}) over SSH ---"
      native_rc=0
      # shellcheck disable=SC2029
      vm_ssh_limited $((VSS_NATIVE_START_TIMEOUT + 60)) "$VSS_SSH_TARGET" \
        "timeout --kill-after=15 ${VSS_NATIVE_START_TIMEOUT} bash '$vm_profile_dir/.scripts/native-services.sh' start ${native_missing[*]}" || native_rc=$?
      if [ "$native_rc" -ne 0 ]; then
        if [ "$native_rc" -eq 124 ] || [ "$native_rc" -eq 143 ]; then
          echo "start.sh: native service startup did not finish within ${VSS_NATIVE_START_TIMEOUT}s (VSS_NATIVE_START_TIMEOUT)." >&2
        else
          echo "start.sh: native service startup on the VM failed (exit $native_rc); see the output above." >&2
        fi
        echo "  If 'nat binary not found': the agent virtualenv is missing - follow 'Agent editable reinstall' in skills/incident-operate-vm/SKILL.md." >&2
        echo "  If the script itself is missing: the VM checkout is behind - run 'git pull' in $VSS_REPO_ROOT." >&2
        exit 1
      fi
    fi

    echo "start.sh: missing services started successfully."
  fi

  echo "=== NEXT STEP — Opening the SSH tunnel (laptop-side, backgrounded) ==="
  for port in 8000 30081 30082 7777; do
    if holder="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}')" && [ -n "$holder" ]; then
      echo "start.sh: laptop port $port is already in use by $holder, so the tunnel cannot forward it." >&2
      echo "  Stop that process (a previous start.sh/tunnel.sh?) and re-run." >&2
      exit 1
    fi
  done
  TUNNEL_LOG="$(mktemp)"
  ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o BatchMode=yes \
    -L 8000:"$VSS_VM_IP":8000 \
    -L 30081:"$VSS_VM_IP":30081 \
    -L 30082:"$VSS_VM_IP":30082 \
    -L 7777:"$VSS_VM_IP":7777 \
    "$VSS_SSH_TARGET" 2>"$TUNNEL_LOG" &
  TUNNEL_PID=$!

  echo "  tunnel pid $TUNNEL_PID; waiting for the tunneled agent health check (localhost:8000/health)..."
  tunnel_ok=""
  tunnel_deadline=$((SECONDS + 60))
  while [ "$SECONDS" -lt "$tunnel_deadline" ]; do
    if curl -sf --max-time 5 http://localhost:8000/health | grep -q isAlive; then
      tunnel_ok=1
      break
    fi
    if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
      break
    fi
    sleep 2
  done
  if [ -z "$tunnel_ok" ]; then
    echo "start.sh: the tunneled agent never came up on localhost:8000." >&2
    # The SSH log repeats one line per failed connection; show each distinct line once.
    tunnel_err="$(sed 's/^channel [0-9]*: //' "$TUNNEL_LOG" | sort -u | head -n 3 | tr '\n' ';')"
    if ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" 'curl -sf --max-time 5 http://localhost:8000/health' 2>/dev/null | grep -q isAlive; then
      echo "  The agent is healthy ON the VM, but the tunnel cannot reach it at ${VSS_VM_IP}:8000${tunnel_err:+ (${tunnel_err})}." >&2
      echo "  Fix: the VM address is wrong or blocked. Re-run with VSS_VM_IP set to the VM's LAN address (ssh $VSS_SSH_TARGET 'ip -4 route get 1.1.1.1')." >&2
    else
      [ -n "$tunnel_err" ] && echo "  SSH tunnel said: ${tunnel_err}" >&2
      echo "  The agent does not answer on the VM either: it crashed after starting. Read its log: ssh $VSS_SSH_TARGET 'tail -n 40 $VSS_REPO_ROOT/.run/vss-agent.log'" >&2
    fi
    echo "  Run ./.scripts/tunnel-check.sh for a per-port breakdown." >&2
    cleanup
    exit 1
  fi
  echo "  agent ok (localhost:8000 -> ${VSS_VM_IP}:8000)"
  echo "  search route ready (POST http://localhost:8000/api/v1/incidents/search, always-on critic)"

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

  # Wait for local mock backend readiness (<5s)
  echo "  waiting for mock backend and search route (http://127.0.0.1:7777/health)..."
  mock_ok=""
  for _i in $(seq 1 10); do
    if curl -sf --max-time 1 http://127.0.0.1:7777/health 2>/dev/null | grep -q isAlive; then
      mock_ok=1
      break
    fi
    sleep 0.5
  done
  if [ -z "$mock_ok" ]; then
    echo "start.sh: mock backend failed to start on http://127.0.0.1:7777 within timeout." >&2
    cleanup
    exit 1
  fi
  echo "  mock backend & search route ok (POST http://127.0.0.1:7777/api/v1/incidents/search)"

  export INCIDENT_AGENT_BASE_URL="http://127.0.0.1:7777"
  export VLM_GATEWAY_URL="http://127.0.0.1:8600"
  export ANALYSIS_MODE="gateway"
fi

echo "  INCIDENT_AGENT_BASE_URL=${INCIDENT_AGENT_BASE_URL}"
if [ -n "${VLM_GATEWAY_URL:-}" ]; then
  echo "  VLM_GATEWAY_URL=${VLM_GATEWAY_URL}"
fi
echo "  ANALYSIS_MODE=${ANALYSIS_MODE}"
echo "  SEARCH_ROUTE=${INCIDENT_AGENT_BASE_URL}/api/v1/incidents/search (always-on)"

if [ "$NO_CONSOLE" = 1 ]; then
  echo "start.sh: --no-console: backend ready; holding the tunnel/local services open. Ctrl-C to stop."
  # wait is interruptible, unlike a foreground sleep loop; with no background job it returns at once.
  wait ${TUNNEL_PID:+"$TUNNEL_PID"} ${MOCK_BACKEND_PID:+"$MOCK_BACKEND_PID"} || true
  exit 0
fi

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