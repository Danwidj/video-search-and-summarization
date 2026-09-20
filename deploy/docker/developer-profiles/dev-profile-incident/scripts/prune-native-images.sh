#!/usr/bin/env bash
#
# prune-native-images.sh — Remove Docker images on kwanz-ws for services
# that now run natively (vss-agent, video-analytics-api, behavior-analytics).
#
# Removes:
#   - nvcr.io/nvidia/vss-core/vss-agent:3.2.1 and dangling vss-agent images
#   - nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1
#   - nvcr.io/nvidia/vss-core/vss-video-analytics-api:3.2.0
#
# Also removes any stopped containers that previously used these images so the
# image layers can be freed cleanly.
#
# Runs on the VM against the local docker daemon.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

echo "=== VM Docker Image Pruning (Native Services Split) ==="
echo "Disk space before pruning:"
df -h / | awk 'NR==1 || NR==2 {print "  " $0}'
echo ""
echo "Docker system disk usage before:"
docker system df | awk '{print "  " $0}'
echo ""

# Safety check: ensure native agent is available before removing Docker agent image
nat_bin="${REPO_ROOT}/services/agent/.venv/bin/nat"
if [ ! -x "${nat_bin}" ]; then
  echo "WARNING: ${nat_bin} does not exist or is not executable." >&2
  echo "  vss-agent should have a valid local .venv before removing its Docker image." >&2
  read -r -p "Proceed with pruning anyway? [y/N] " confirm
  if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
  fi
fi

# 1. Stop and remove containers associated with native services
containers_to_remove=(
  "vss-agent"
  "mdx-vss-agent-1"
  "vss-video-analytics-api"
  "vss-video-analytics-api-fusion"
  "mdx-vss-video-analytics-api-1"
  "mdx-vss-video-analytics-api-fusion-1"
  "vss-behavior-analytics"
  "vss-search-analytics-2d-fusion"
  "mdx-vss-behavior-analytics-1"
  "mdx-vss-search-analytics-2d-fusion-1"
)

echo "Checking for stopped containers using native service images..."
for c in "${containers_to_remove[@]}"; do
  if docker ps -a --format '{{.Names}}' | grep -E "^${c}$" >/dev/null 2>&1; then
    echo "  Removing container ${c}..."
    docker rm -f "${c}" 2>/dev/null || true
  fi
done

# Also remove any container created from the specific images
images_to_remove=(
  "nvcr.io/nvidia/vss-core/vss-agent:3.2.1"
  "nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1"
  "nvcr.io/nvidia/vss-core/vss-video-analytics-api:3.2.0"
)

for img in "${images_to_remove[@]}"; do
  c_ids="$(docker ps -a --filter "ancestor=${img}" --format '{{.ID}}')"
  if [ -n "${c_ids}" ]; then
    echo "  Removing leftover containers for image ${img}: ${c_ids}"
    # shellcheck disable=SC2086
    docker rm -f ${c_ids} 2>/dev/null || true
  fi
done

# 2. Remove specified images
echo ""
echo "Removing native service Docker images..."
for img in "${images_to_remove[@]}"; do
  if docker images --format '{{.Repository}}:{{.Tag}}' | grep -F "${img}" >/dev/null 2>&1; then
    echo "  Removing image ${img}..."
    docker rmi "${img}" 2>/dev/null || true
  else
    echo "  Image ${img} not found, skipping."
  fi
done

# 3. Remove dangling vss-agent / analytics images
echo ""
echo "Pruning dangling vss-agent and analytics images..."
dangling_agent_ids="$(docker images -f "dangling=true" --format '{{.ID}} {{.Repository}}' | grep -E 'vss-agent|analytics' | awk '{print $1}' || true)"
if [ -n "${dangling_agent_ids}" ]; then
  echo "  Removing dangling images: ${dangling_agent_ids}"
  # shellcheck disable=SC2086
  docker rmi ${dangling_agent_ids} 2>/dev/null || true
fi

# Prune general dangling images
docker image prune -f --filter "until=24h" >/dev/null 2>&1 || true

echo ""
echo "Disk space after pruning:"
df -h / | awk 'NR==1 || NR==2 {print "  " $0}'
echo ""
echo "Docker system disk usage after:"
docker system df | awk '{print "  " $0}'
echo ""
echo "=== Pruning Complete ==="
