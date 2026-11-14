#!/usr/bin/env bash
#
# start.sh: the one-command laptop entry point for the incident profile. Run it from
# your laptop, never on the VM:
#
#   cd deploy/docker/developer-profiles/dev-profile-incident
#   ./start.sh [--mode mock|vm] [--no-console] [--prod]
#
#   --mode vm      default: checks and heals the VM backend over SSH, opens the SSH
#                  tunnel to the agent (:8000) and starts incident-console-v2 (:3200)
#   --mode mock    laptop only, no VM or SSH: mock-backend (:7777) and vlm-gateway (:8600)
#   --no-console   backend and tunnel only
#   --prod         console as a production build (rebuilt on every run)
#
# Ctrl-C stops every laptop process and the tunnel; nothing on the shared VM stops.
# Modes, settings (VSS_SSH_HOST, ENABLE_TRACKING, timeouts, ...) and the VM flow:
# .docs/incident-profile-operations.md section 3 and skills/incident-start/SKILL.md.
set -euo pipefail

# Pin all local processes and defaults to GPU 0 to protect GPU 1 for co-tenants
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export NVIDIA_VISIBLE_DEVICES="${NVIDIA_VISIBLE_DEVICES:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse --mode / --no-console flags (--no-console: bring the backend and tunnel up, skip the Next.js console)
NO_CONSOLE=0
PROD=0
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
    --prod)
      PROD=1
      shift
      ;;
    *)
      echo "start.sh: unknown argument '$1'" >&2
      echo "Usage: ./start.sh [--mode mock|vm] [--no-console] [--prod]" >&2
      exit 1
      ;;
  esac
done

case "$VSS_START_MODE" in
  vm|mock) ;;
  *)
    echo "start.sh: VSS_START_MODE must be 'vm' or 'mock' (got '$VSS_START_MODE')." >&2
    exit 1
    ;;
esac

# VM host: VSS_SSH_HOST from the environment or .env.local, no default. Mock mode never
# SSHes, so it needs the host only for the laptop guard below, when one is configured.
# shellcheck source=.scripts/vm-host.sh
source "${SCRIPT_DIR}/.scripts/vm-host.sh"
if [ "$VSS_START_MODE" = vm ]; then
  vm_require_ssh_host start.sh || exit 1
else
  vm_load_ssh_host
fi

# Laptop-side only: refuse to run ON the VM
if vm_running_on_host; then
  echo "start.sh: run this from your laptop, not on the VM (it SSHes to the VM, forwards laptop ports to it, and runs v2 locally)." >&2
  exit 1
fi

TUNNEL_PID=""
TUNNEL_LOG=""
MOCK_BACKEND_PID=""
VLM_GATEWAY_PID=""
CONSOLE_PID=""
CLEANUP_RUNNING=""

# Every process below pid, found through parent pids (pgrep -P works on Linux and macOS).
descendants() {
  local child
  for child in $(pgrep -P "$1" 2>/dev/null); do
    echo "$child"
    descendants "$child"
  done
}

# Stops a background job and everything it started. The job pid is only the
# wrapper (uv, npm); its children (uvicorn, next dev, next-server) keep
# listening when only the wrapper is killed. The tree is listed before any
# kill, because a killed parent's children are re-parented and lost to pgrep.
stop_tree() {
  local pids
  pids="$1 $(descendants "$1" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
}

cleanup() {
  if [ -n "$CLEANUP_RUNNING" ]; then
    return
  fi
  CLEANUP_RUNNING=1

  if [ -n "${VM_SSH_PID:-}" ] && kill -0 "$VM_SSH_PID" 2>/dev/null; then
    kill "$VM_SSH_PID" 2>/dev/null || true
    VM_SSH_PID=""
  fi
  [ -n "$TUNNEL_LOG" ] && rm -f "$TUNNEL_LOG"
  if [ -n "$CONSOLE_PID" ] && kill -0 "$CONSOLE_PID" 2>/dev/null; then
    stop_tree "$CONSOLE_PID"
    echo "start.sh: stopped incident-console-v2 (pid $CONSOLE_PID)."
    CONSOLE_PID=""
  fi
  if [ -n "$VLM_GATEWAY_PID" ] && kill -0 "$VLM_GATEWAY_PID" 2>/dev/null; then
    stop_tree "$VLM_GATEWAY_PID"
    echo "start.sh: stopped the local vlm-gateway (pid $VLM_GATEWAY_PID)."
    VLM_GATEWAY_PID=""
  fi
  if [ -n "$MOCK_BACKEND_PID" ] && kill -0 "$MOCK_BACKEND_PID" 2>/dev/null; then
    stop_tree "$MOCK_BACKEND_PID"
    echo "start.sh: stopped the local mock backend (pid $MOCK_BACKEND_PID)."
    MOCK_BACKEND_PID=""
  fi
  if [ -n "$TUNNEL_PID" ] && kill -0 "$TUNNEL_PID" 2>/dev/null; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    echo "start.sh: closed the backgrounded SSH tunnel (pid $TUNNEL_PID)."
    TUNNEL_PID=""
  fi
}
trap cleanup EXIT INT TERM HUP

start_vlm_gateway() {
  echo "=== Starting local vlm-gateway (:8600) ==="
  (
    cd "${SCRIPT_DIR}/vlm-gateway"
    uv sync
    exec uv run --env-file "${SCRIPT_DIR}/vlm-gateway/.env.local" \
      uvicorn app:app --host 127.0.0.1 --port 8600
  ) &
  VLM_GATEWAY_PID=$!
}

if [ "$VSS_START_MODE" = "vm" ]; then
  VSS_REPO_ROOT="${VSS_REPO_ROOT:-/srv/rise-up/vss}"
  ENABLE_ANALYTICS="${ENABLE_ANALYTICS:-false}"
  ENABLE_TRACKING="${ENABLE_TRACKING:-true}"

  # Docker appliances: only Phoenix (VIOS/VST, HAProxy, Redis and Kafka were dropped)
  default_docker_services="phoenix"
  if [ "${ENABLE_ANALYTICS}" = "true" ]; then
    default_docker_services="${default_docker_services} elasticsearch"
  fi
  INCIDENT_DOCKER_SERVICES="${INCIDENT_DOCKER_SERVICES:-$default_docker_services}"

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

  VSS_PULL_TIMEOUT="${VSS_PULL_TIMEOUT:-1800}"
  VSS_COMPOSE_UP_TIMEOUT="${VSS_COMPOSE_UP_TIMEOUT:-600}"
  VSS_NATIVE_START_TIMEOUT="${VSS_NATIVE_START_TIMEOUT:-300}"
  VSS_REPO_URL="${VSS_REPO_URL:-$(git -C "$SCRIPT_DIR" remote get-url origin 2>/dev/null || true)}"
  # A token embedded in the remote (https://user:token@host/...) must not reach the VM's process list or the terminal.
  VSS_REPO_URL="$(printf '%s' "$VSS_REPO_URL" | sed -E 's#^(https?://)[^/@]+@#\1#')"
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
  if [ -z "$native_output" ]; then
    echo "(no services)"
  else
    # shellcheck disable=SC2029
    ssh "${VSS_SSH_OPTS[@]}" "$VSS_SSH_TARGET" \
      "timeout 60 bash '$vm_profile_dir/.scripts/native-services.sh' status" 2>&1 || true
  fi

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
      compose_services=("${docker_missing[@]}")
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

  if [ "$ENABLE_TRACKING" = "true" ]; then
    echo "=== Person-tracking stack (ENABLE_TRACKING=true) ==="
    tracking_rc=0
    # shellcheck disable=SC2029
    vm_ssh_limited $((VSS_COMPOSE_UP_TIMEOUT + 900)) "$VSS_SSH_TARGET" \
      "bash '$vm_profile_dir/.scripts/tracking-stack.sh' start" || tracking_rc=$?
    if [ "$tracking_rc" -ne 0 ]; then
      echo "start.sh: the tracking stack did not come up (exit $tracking_rc); see the [tracking] lines above." >&2
      exit 1
    fi
  fi

  echo "=== NEXT STEP — Opening the SSH tunnel (laptop-side, backgrounded) ==="
  if holder="$(lsof -nP -iTCP:8000 -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1" (pid "$2")"}')" && [ -n "$holder" ]; then
    echo "start.sh: laptop port 8000 is already in use by $holder, so the tunnel cannot forward it." >&2
    echo "  Stop that process (a previous start.sh/tunnel.sh?) and re-run." >&2
    exit 1
  fi
  TUNNEL_LOG="$(mktemp)"
  ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o BatchMode=yes \
    -L 8000:127.0.0.1:8000 \
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
      echo "  The agent is healthy ON the VM, but the tunnel cannot reach it at the VM loopback :8000${tunnel_err:+ (${tunnel_err})}." >&2
      echo "  Fix: the SSH connection or forward is blocked; check the SSH target. If VSS_AGENT_HOST on the VM is set to a LAN address instead of 127.0.0.1, unset it and restart the agent." >&2
    else
      [ -n "$tunnel_err" ] && echo "  SSH tunnel said: ${tunnel_err}" >&2
      echo "  The agent does not answer on the VM either: it crashed after starting. Read its log: ssh $VSS_SSH_TARGET 'tail -n 40 $VSS_REPO_ROOT/.run/vss-agent.log'" >&2
    fi
    echo "  Run ./.scripts/tunnel-check.sh for a per-port breakdown." >&2
    cleanup
    exit 1
  fi
  echo "  agent ok (localhost:8000 -> VM loopback :8000)"
  echo "  search route ready (POST http://localhost:8000/api/v1/incidents/search, critic off by default)"


  export INCIDENT_AGENT_BASE_URL="http://localhost:8000"
  export ANALYSIS_MODE="agent"

  # No local vlm-gateway here: the agent does the analysis and reads the dashboard's chart requests
  # with its own LLM, so this laptop needs no gateway key.
elif [ "$VSS_START_MODE" = "mock" ]; then
  # Each local service reads its own .env.local symlink to the shared
  # ../.env.local (incident-start skill, kept in place by .githooks/setup-worktree.sh).
  for env_link in mock-backend/.env.local vlm-gateway/.env.local; do
    if [ ! -f "${SCRIPT_DIR}/${env_link}" ]; then
      echo "start.sh: ${env_link} is missing or does not resolve to the shared .env.local." >&2
      echo "  Fix: (cd \"${SCRIPT_DIR}\" && ln -sfn ../.env.local ${env_link})" >&2
      exit 1
    fi
  done

  echo "=== Starting local mock backend (mock-backend/base_profile_mock, :7777) ==="
  (
    cd "${SCRIPT_DIR}/mock-backend/base_profile_mock"
    uv sync
    exec uv run --env-file "${SCRIPT_DIR}/mock-backend/.env.local" \
      uvicorn base_profile_mock.app:create_app --factory --host 127.0.0.1 --port 7777
  ) &
  MOCK_BACKEND_PID=$!

  start_vlm_gateway

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
echo "  SEARCH_ROUTE=${INCIDENT_AGENT_BASE_URL}/api/v1/incidents/search (always mounted)"

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

# A background job and wait, not a foreground command: bash runs a trap only
# after the foreground command returns, so a SIGTERM to start.sh alone would
# wait on npm forever. wait returns as soon as a trapped signal arrives.
if [ "$PROD" = 1 ]; then
  echo "start.sh: console mode: PRODUCTION (--prod): running 'next build' first (about a minute), then 'next start'."
  npm run build &
  CONSOLE_PID=$!
  build_rc=0
  wait "$CONSOLE_PID" || build_rc=$?
  CONSOLE_PID=""
  if [ "$build_rc" -ne 0 ]; then
    echo "start.sh: 'next build' failed (exit ${build_rc}); not starting the console. Fix the build, or run without --prod." >&2
    cleanup
    exit "$build_rc"
  fi
  echo "  v2 (production build) running at http://localhost:3200 — Ctrl-C here (or close this terminal) stops v2 and any backgrounded local services/tunnel."
  npm run start -- -H 127.0.0.1 --port 3200 &
else
  echo "start.sh: console mode: development (next dev); add --prod for a production build."
  echo "  v2 running at http://localhost:3200 — Ctrl-C here (or close this terminal) stops v2 and any backgrounded local services/tunnel."
  npm run dev -- -H 127.0.0.1 --port 3200 &
fi
CONSOLE_PID=$!
console_rc=0
wait "$CONSOLE_PID" || console_rc=$?
cleanup
exit "$console_rc"
