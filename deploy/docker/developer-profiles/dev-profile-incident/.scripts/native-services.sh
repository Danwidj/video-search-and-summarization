#!/usr/bin/env bash
#
# native-services.sh — Control script for managing native processes on kwanz-ws
# (vss-agent, video-analytics-api, behavior-analytics)
#
# Usage:
#   ./native-services.sh start [service...]
#   ./native-services.sh stop [service...]
#   ./native-services.sh restart [service...]
#   ./native-services.sh status [--porcelain] [service...]
#   ./native-services.sh logs [service] [-f]
#
# Services supported:
#   - vss-agent (default port 8000)
#   - video-analytics-api (default port 8081)
#   - behavior-analytics (default port 8080)
#
# Specifying "all" targets all 3 services.
# Specifying "analytics" targets video-analytics-api and behavior-analytics.
# Default 'start' without arguments starts vss-agent (plus analytics if ENABLE_ANALYTICS=true).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

# Ensure common user binary locations are on PATH
export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:/usr/local/bin:${PATH}"

# Directory for PID files and log output
RUN_DIR="${VSS_RUN_DIR:-${REPO_ROOT}/.run}"
mkdir -p "${RUN_DIR}"

# -----------------------------------------------------------------------------
# Environment loading
# -----------------------------------------------------------------------------
load_env() {
  local env_file="${ENV_FILE:-}"
  if [ -z "${env_file}" ]; then
    if [ -f "${REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote" ]; then
      env_file="${REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote"
    elif [ -f "${REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/.env" ]; then
      env_file="${REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-incident/.env"
    else
      env_file="$(command ls "${REPO_ROOT}"/deploy/docker/developer-profiles/dev-profile-*/generated.env* 2>/dev/null | head -1 || true)"
    fi
  fi

  if [ -n "${env_file}" ] && [ -f "${env_file}" ]; then
    # Export vars from env file safely, ignoring comments and blanks
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi
}

load_env

# -----------------------------------------------------------------------------
# Service Helpers
# -----------------------------------------------------------------------------
get_pid() {
  local svc="$1"
  local pid_file="${RUN_DIR}/${svc}.pid"
  if [ -f "${pid_file}" ]; then
    local pid
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
      echo "${pid}"
      return 0
    fi
  fi
  echo ""
}

is_running() {
  local svc="$1"
  local pid
  pid="$(get_pid "${svc}")"
  [ -n "${pid}" ]
}

# -----------------------------------------------------------------------------
# vss-agent
# -----------------------------------------------------------------------------
start_vss_agent() {
  local svc="vss-agent"
  if is_running "${svc}"; then
    echo "  ${svc} is already running (pid $(get_pid "${svc}"))"
    return 0
  fi

  local nat_bin="${REPO_ROOT}/services/agent/.venv/bin/nat"
  if [ ! -x "${nat_bin}" ]; then
    echo "ERROR: nat binary not found or not executable at ${nat_bin}" >&2
    echo "  Ensure /services/agent/.venv is created and nat is installed." >&2
    return 1
  fi

  local cfg="${VSS_AGENT_CONFIG_FILE:-${REPO_ROOT}/deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml}"
  if [[ "${cfg}" != /* ]]; then
    cfg="${REPO_ROOT}/${cfg}"
  fi
  if [ ! -f "${cfg}" ]; then
    echo "ERROR: vss-agent config file not found: ${cfg}" >&2
    return 1
  fi

  local host="${VSS_AGENT_HOST:-0.0.0.0}"
  local port="${VSS_AGENT_PORT:-8000}"
  local log_file="${RUN_DIR}/${svc}.log"
  local pid_file="${RUN_DIR}/${svc}.pid"

  echo "  Starting ${svc} (host=${host}, port=${port})..."
  echo "    command: ${nat_bin} serve --config_file ${cfg} --host ${host} --port ${port}"
  echo "    logging: ${log_file}"

  (
    cd "${REPO_ROOT}"
    # shellcheck disable=SC2086
    nohup "${nat_bin}" serve --config_file "${cfg}" --host "${host}" --port "${port}" > "${log_file}" 2>&1 &
    echo $! > "${pid_file}"
  )

  local pid
  pid="$(cat "${pid_file}")"
  echo "    launched with pid ${pid}; waiting for healthcheck (http://localhost:${port}/health)..."

  local healthy=""
  for _ in $(seq 1 45); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      echo "ERROR: ${svc} process (pid ${pid}) exited unexpectedly. Log tail:" >&2
      tail -n 20 "${log_file}" >&2
      rm -f "${pid_file}"
      return 1
    fi
    if curl -sf --max-time 3 "http://localhost:${port}/health" 2>/dev/null | grep -q "isAlive"; then
      healthy="1"
      break
    fi
    sleep 2
  done

  if [ -z "${healthy}" ]; then
    echo "ERROR: ${svc} did not pass healthcheck on port ${port} within timeout. Log tail:" >&2
    tail -n 30 "${log_file}" >&2
    return 1
  fi

  echo "  ${svc} is UP and healthy (pid ${pid}, port ${port})"
}

# -----------------------------------------------------------------------------
# video-analytics-api
# -----------------------------------------------------------------------------
start_video_analytics_api() {
  local svc="video-analytics-api"
  if is_running "${svc}"; then
    echo "  ${svc} is already running (pid $(get_pid "${svc}"))"
    return 0
  fi

  local app_dir="${REPO_ROOT}/services/analytics/video-analytics-api/src/app"
  if [ ! -d "${app_dir}" ]; then
    echo "ERROR: ${svc} app dir not found at ${app_dir}" >&2
    return 1
  fi

  local node_bin
  node_bin="$(which node 2>/dev/null || true)"
  if [ -z "${node_bin}" ]; then
    for candidate in "${HOME}/.local/bin/node" "${HOME}/.nvm/versions/node"/*/bin/node /usr/local/bin/node /usr/bin/node; do
      if [ -x "${candidate}" ]; then
        node_bin="${candidate}"
        break
      fi
    done
  fi
  if [ -z "${node_bin}" ]; then
    echo "ERROR: node binary not found on PATH or standard locations." >&2
    return 1
  fi

  local cfg="${VSS_VIDEO_ANALYTICS_API_CONFIG_FILE:-}"
  if [ -z "${cfg}" ]; then
    if [ -f "${REPO_ROOT}/services/analytics/video-analytics-api/configs/vss-video-analytics-api-config.json" ]; then
      cfg="${REPO_ROOT}/services/analytics/video-analytics-api/configs/vss-video-analytics-api-config.json"
    else
      cfg="${REPO_ROOT}/services/analytics/video-analytics-api/configs/default-configs/config.json"
    fi
  fi
  if [[ "${cfg}" != /* ]]; then
    cfg="${REPO_ROOT}/${cfg}"
  fi

  local port="8081"
  local log_file="${RUN_DIR}/${svc}.log"
  local pid_file="${RUN_DIR}/${svc}.pid"

  echo "  Starting ${svc} on port ${port}..."
  echo "    command: ${node_bin} index.js --config ${cfg}"
  echo "    logging: ${log_file}"

  (
    cd "${app_dir}"
    nohup "${node_bin}" index.js --config "${cfg}" > "${log_file}" 2>&1 &
    echo $! > "${pid_file}"
  )

  local pid
  pid="$(cat "${pid_file}")"
  echo "    launched with pid ${pid}; waiting for service startup..."

  local healthy=""
  for _ in $(seq 1 15); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      echo "ERROR: ${svc} process (pid ${pid}) exited unexpectedly. Log tail:" >&2
      tail -n 20 "${log_file}" >&2
      rm -f "${pid_file}"
      return 1
    fi
    if curl -sf --max-time 2 "http://localhost:${port}/" >/dev/null 2>&1 || curl -sf --max-time 2 "http://localhost:${port}/livez" >/dev/null 2>&1 || grep -q "Listening on port: ${port}" "${log_file}" 2>/dev/null; then
      healthy="1"
      break
    fi
    sleep 1
  done

  if [ -z "${healthy}" ]; then
    echo "WARNING: ${svc} (pid ${pid}) started, but port ${port} did not respond yet. Check logs with: ./native-services.sh logs ${svc}"
  else
    echo "  ${svc} is UP (pid ${pid}, port ${port})"
  fi
}

# -----------------------------------------------------------------------------
# behavior-analytics
# -----------------------------------------------------------------------------
start_behavior_analytics() {
  local svc="behavior-analytics"
  if is_running "${svc}"; then
    echo "  ${svc} is already running (pid $(get_pid "${svc}"))"
    return 0
  fi

  local app_dir="${REPO_ROOT}/services/analytics/behavior-analytics"
  if [ ! -d "${app_dir}" ]; then
    echo "ERROR: ${svc} directory not found at ${app_dir}" >&2
    return 1
  fi

  local py_bin="${app_dir}/.venv/bin/python3"
  if [ ! -x "${py_bin}" ]; then
    py_bin="$(which python3 2>/dev/null || true)"
  fi
  if [ -z "${py_bin}" ]; then
    echo "ERROR: python3 binary not found for ${svc}" >&2
    return 1
  fi

  local cfg="${VSS_BEHAVIOR_ANALYTICS_CONFIG_FILE:-}"
  if [ -z "${cfg}" ]; then
    if [ -f "${app_dir}/configs/vss-behavior-analytics-config.json" ]; then
      cfg="${app_dir}/configs/vss-behavior-analytics-config.json"
    elif [ -f "${app_dir}/configs/warehouse_2d_config.json" ]; then
      cfg="${app_dir}/configs/warehouse_2d_config.json"
    else
      cfg="${app_dir}/configs/dev_example_config.json"
    fi
  fi
  if [[ "${cfg}" != /* ]]; then
    cfg="${REPO_ROOT}/${cfg}"
  fi

  local app_script="${VSS_BEHAVIOR_ANALYTICS_APP:-apps/analytics/main_analytics_2d_app.py}"
  local port="8080"
  local log_file="${RUN_DIR}/${svc}.log"
  local pid_file="${RUN_DIR}/${svc}.pid"

  echo "  Starting ${svc} (port=${port})..."
  echo "    command: PYTHONPATH=src ${py_bin} ${app_script} --config ${cfg}"
  echo "    logging: ${log_file}"

  (
    cd "${app_dir}"
    nohup env PYTHONPATH="src:${PYTHONPATH:-}" "${py_bin}" "${app_script}" --config "${cfg}" > "${log_file}" 2>&1 &
    echo $! > "${pid_file}"
  )

  local pid
  pid="$(cat "${pid_file}")"
  echo "    launched with pid ${pid}; checking process health..."

  sleep 3
  if ! kill -0 "${pid}" 2>/dev/null; then
    echo "ERROR: ${svc} process (pid ${pid}) exited immediately. Log tail:" >&2
    tail -n 25 "${log_file}" >&2
    rm -f "${pid_file}"
    return 1
  fi

  echo "  ${svc} is UP (pid ${pid}, port ${port})"
}

# -----------------------------------------------------------------------------
# Stop helper
# -----------------------------------------------------------------------------
stop_service() {
  local svc="$1"
  local pid_file="${RUN_DIR}/${svc}.pid"
  local pid
  pid="$(get_pid "${svc}")"

  if [ -z "${pid}" ]; then
    # Check if a stale pid file exists
    if [ -f "${pid_file}" ]; then
      rm -f "${pid_file}"
    fi
    echo "  ${svc}: not running"
    return 0
  fi

  echo "  Stopping ${svc} (pid ${pid})..."
  kill -15 "${pid}" 2>/dev/null || true

  local stopped=""
  for _ in $(seq 1 10); do
    if ! kill -0 "${pid}" 2>/dev/null; then
      stopped="1"
      break
    fi
    sleep 1
  done

  if [ -z "${stopped}" ]; then
    echo "    pid ${pid} did not stop gracefully; sending SIGKILL..."
    kill -9 "${pid}" 2>/dev/null || true
  fi

  rm -f "${pid_file}"
  echo "  ${svc}: stopped"
}

# -----------------------------------------------------------------------------
# Status helper
# -----------------------------------------------------------------------------
status_service() {
  local svc="$1"
  local porcelain="${2:-false}"
  local pid
  pid="$(get_pid "${svc}")"

  local port="unknown"
  case "${svc}" in
    vss-agent) port="${VSS_AGENT_PORT:-8000}" ;;
    video-analytics-api) port="8081" ;;
    behavior-analytics) port="8080" ;;
  esac

  if [ "${porcelain}" = "true" ]; then
    if [ -n "${pid}" ]; then
      echo "${svc}:running:${pid}:${port}"
    else
      echo "${svc}:stopped:none:${port}"
    fi
  else
    if [ -n "${pid}" ]; then
      local health_note=""
      if [ "${svc}" = "vss-agent" ]; then
        if curl -sf --max-time 2 "http://localhost:${port}/health" 2>/dev/null | grep -q "isAlive"; then
          health_note=" (healthy)"
        else
          health_note=" (unresponsive)"
        fi
      fi
      printf "  %-22s RUNNING  (pid %-7s port %-5s)%s\n" "${svc}" "${pid}" "${port}" "${health_note}"
    else
      printf "  %-22s STOPPED  (port %s)\n" "${svc}" "${port}"
    fi
  fi
}

# -----------------------------------------------------------------------------
# Action routing
# -----------------------------------------------------------------------------
ACTION="${1:-status}"
shift || true

PORCELAIN=false
SERVICES=()

for arg in "$@"; do
  if [ "${arg}" = "--porcelain" ]; then
    PORCELAIN=true
  else
    SERVICES+=("${arg}")
  fi
done

# Expand shorthand targets
resolve_services() {
  local input=("$@")
  local resolved=()
  for item in "${input[@]}"; do
    case "${item}" in
      all)
        resolved+=("vss-agent" "video-analytics-api" "behavior-analytics")
        ;;
      analytics)
        resolved+=("video-analytics-api" "behavior-analytics")
        ;;
      *)
        resolved+=("${item}")
        ;;
    esac
  done
  echo "${resolved[@]}"
}

case "${ACTION}" in
  start)
    if [ "${#SERVICES[@]}" -eq 0 ]; then
      TARGETS=("vss-agent")
      if [ "${ENABLE_ANALYTICS:-false}" = "true" ]; then
        TARGETS+=("video-analytics-api" "behavior-analytics")
      fi
    else
      read -r -a TARGETS <<< "$(resolve_services "${SERVICES[@]}")"
    fi

    echo "=== Starting Native Services ==="
    for svc in "${TARGETS[@]}"; do
      case "${svc}" in
        vss-agent) start_vss_agent ;;
        video-analytics-api) start_video_analytics_api ;;
        behavior-analytics) start_behavior_analytics ;;
        *)
          echo "WARNING: Unknown native service '${svc}' (supported: vss-agent, video-analytics-api, behavior-analytics)" >&2
          ;;
      esac
    done
    ;;

  stop)
    if [ "${#SERVICES[@]}" -eq 0 ]; then
      TARGETS=("vss-agent" "video-analytics-api" "behavior-analytics")
    else
      read -r -a TARGETS <<< "$(resolve_services "${SERVICES[@]}")"
    fi

    echo "=== Stopping Native Services ==="
    for svc in "${TARGETS[@]}"; do
      stop_service "${svc}"
    done
    ;;

  restart)
    if [ "${#SERVICES[@]}" -eq 0 ]; then
      TARGETS=("vss-agent")
      if [ "${ENABLE_ANALYTICS:-false}" = "true" ]; then
        TARGETS+=("video-analytics-api" "behavior-analytics")
      fi
    else
      read -r -a TARGETS <<< "$(resolve_services "${SERVICES[@]}")"
    fi

    echo "=== Restarting Native Services ==="
    for svc in "${TARGETS[@]}"; do
      stop_service "${svc}"
      case "${svc}" in
        vss-agent) start_vss_agent ;;
        video-analytics-api) start_video_analytics_api ;;
        behavior-analytics) start_behavior_analytics ;;
      esac
    done
    ;;

  status)
    if [ "${#SERVICES[@]}" -eq 0 ]; then
      TARGETS=("vss-agent" "video-analytics-api" "behavior-analytics")
    else
      read -r -a TARGETS <<< "$(resolve_services "${SERVICES[@]}")"
    fi

    if [ "${PORCELAIN}" != "true" ]; then
      echo "=== Native Services Status (kwanz-ws) ==="
    fi
    for svc in "${TARGETS[@]}"; do
      status_service "${svc}" "${PORCELAIN}"
    done
    ;;

  logs)
    target_svc="${SERVICES[0]:-vss-agent}"
    log_file="${RUN_DIR}/${target_svc}.log"
    if [ ! -f "${log_file}" ]; then
      echo "No log file found for ${target_svc} at ${log_file}" >&2
      exit 1
    fi
    shift || true
    exec tail -n 100 -f "${log_file}"
    ;;

  *)
    echo "Usage: $0 {start|stop|restart|status|logs} [service...] [--porcelain]" >&2
    exit 1
    ;;
esac
