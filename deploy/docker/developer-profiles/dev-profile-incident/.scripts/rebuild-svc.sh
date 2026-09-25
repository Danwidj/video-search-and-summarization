#!/usr/bin/env bash
#
# Fast single-service rebuild or restart (no full stack teardown/redeploy).
#
# If target is a native service (vss-agent, video-analytics-api, behavior-analytics),
# restarts it natively in ~2s via native-services.sh without Docker build overhead.
#
# If target is a Docker appliance service, recreates it via:
#   docker compose up -d --build --force-recreate <service>
#
# Runs on the VM against the local process manager and docker daemon.
#
# Usage: ./rebuild-svc.sh <service> [more services...]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

if [ -z "${1:-}" ]; then
  echo "usage: rebuild-svc.sh <service> [more services...]" >&2
  echo "  Native services: vss-agent, video-analytics-api, behavior-analytics" >&2
  echo "  Docker services: vss-vios-streamprocessing, vss-vios-ingress, etc." >&2
  exit 1
fi

native_svcs=()
docker_svcs=()

for arg in "$@"; do
  case "${arg}" in
    vss-agent|video-analytics-api|behavior-analytics|analytics)
      native_svcs+=("${arg}")
      ;;
    *)
      docker_svcs+=("${arg}")
      ;;
  esac
done

if [ "${#native_svcs[@]}" -gt 0 ]; then
  echo "=== Restarting native service(s): ${native_svcs[*]} ==="
  "${SCRIPT_DIR}/native-services.sh" restart "${native_svcs[@]}"
fi

if [ "${#docker_svcs[@]}" -gt 0 ]; then
  echo "=== Rebuilding Docker service(s): ${docker_svcs[*]} ==="
  compose_dir="${REPO_ROOT}/deploy/docker"
  generated_env="$(command ls "${compose_dir}"/developer-profiles/dev-profile-*/generated.env* 2>/dev/null | head -1 || true)"
  if [ -z "${generated_env}" ]; then
    echo "rebuild-svc.sh: no active profile found (no generated.env under" >&2
    echo "  ${compose_dir}/developer-profiles/) — is a profile currently up?" >&2
    exit 1
  fi

  (cd "${compose_dir}" && docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file "${generated_env}" -p mdx up -d --scale init-dirs=0 --scale render-config=0 --scale wdm-env-from-config=0 --scale sdr-controller=0 --build --force-recreate "${docker_svcs[@]}")
fi
