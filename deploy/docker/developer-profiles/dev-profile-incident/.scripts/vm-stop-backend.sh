#!/usr/bin/env bash
#
# vm-stop-backend.sh - runs ON THE VM. start.sh pipes it over SSH
# (`ssh host bash -s -- <args> < vm-stop-backend.sh`), so the latest laptop copy
# is always the one that runs, even when the VM checkout is behind.
#
# Usage: vm-stop-backend.sh <lock-file> <repo-root> <docker-services> <native-services>
#
# Checks if any other start.sh session is holding a shared lock on <lock-file>.
# If an exclusive lock can be acquired, this is the last active session:
#   1. Stops the expected native services via native-services.sh stop
#   2. Stops the expected Docker appliance containers via docker stop
# Containers are only stopped, never removed or deleted. Data/volumes are preserved.
# If another session holds a shared lock, exits 0 without stopping anything.

set -uo pipefail

# Pin all Docker operations / subprocesses to GPU 0 to protect GPU 1 for co-tenants
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export NVIDIA_VISIBLE_DEVICES="${NVIDIA_VISIBLE_DEVICES:-0}"

LOCK_FILE="${1:?lock file}"
REPO_ROOT="${2:?repo root}"
DOCKER_SERVICES="${3:-}"
NATIVE_SERVICES="${4:-}"

# Ensure lock file and directory exist with world-writable permissions
if [ ! -r "$LOCK_FILE" ]; then
  mkdir -p "$(dirname "$LOCK_FILE")" 2>/dev/null || true
  touch "$LOCK_FILE" 2>/dev/null || true
  chmod 777 "$(dirname "$LOCK_FILE")" 2>/dev/null || true
  chmod 666 "$LOCK_FILE" 2>/dev/null || true
fi

# Open fd 200 for reading
exec 200<"$LOCK_FILE"

# Try non-blocking exclusive lock (with brief wait for tearing-down connections to settle)
if ! flock -x -w 1 200 2>/dev/null && ! flock -x -n 200 2>/dev/null; then
  echo "start.sh: other active sessions remain on the VM; leaving backend running."
  exit 0
fi

# We now hold the exclusive lock on fd 200
echo "start.sh: last active session exited; stopping backend services on the VM..."

# 1. Stop native services (vss-agent, etc.)
if [ -n "$NATIVE_SERVICES" ]; then
  native_script="$REPO_ROOT/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh"
  if [ -f "$native_script" ]; then
    echo "--- Stopping Native Services (${NATIVE_SERVICES}) ---"
    # shellcheck disable=SC2086
    bash "$native_script" stop ${NATIVE_SERVICES} || {
      echo "start.sh: warning: native-services.sh stop exited with $?" >&2
    }
  else
    echo "start.sh: warning: native-services.sh not found at $native_script; skipping native stop." >&2
  fi
fi

# 2. Stop Docker appliance containers
if [ -n "$DOCKER_SERVICES" ]; then
  DOCKER=(docker)
  if ! timeout 30 docker info >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null && timeout 30 sudo -n docker info >/dev/null 2>&1; then
      DOCKER=(sudo -n docker)
    fi
  fi

  # The laptop-side service names are the compose service names
  read -r -a compose_svcs <<<"${DOCKER_SERVICES}"

  containers_to_stop=()
  if [ -f "$REPO_ROOT/deploy/docker/compose.yml" ]; then
    while read -r cid; do
      [ -n "$cid" ] && containers_to_stop+=("$cid")
    done < <(cd "$REPO_ROOT/deploy/docker" && "${DOCKER[@]}" compose -p mdx ps -q "${compose_svcs[@]}" 2>/dev/null || true)
  fi

  if [ ${#containers_to_stop[@]} -gt 0 ]; then
    echo "--- Stopping Docker Containers (${containers_to_stop[*]}) ---"
    "${DOCKER[@]}" stop "${containers_to_stop[@]}" || {
      echo "start.sh: warning: docker stop exited with $?" >&2
    }
  else
    echo "start.sh: no expected Docker containers are currently running."
  fi
fi

echo "start.sh: backend services stopped successfully."
exit 0
