#!/usr/bin/env bash
#
# Prove the tunnel is up from the laptop end (replaces the old
# `mdx-tunnel-incident-check` shell alias from deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh —
# same behavior, standalone script). LAPTOP SIDE ONLY, like tunnel.sh.
#
# The agent health check must pass; the NIM endpoints only need to answer at
# HTTP level — any status code proves the forward works (a 4xx from the NIM
# is still the NIM answering).

VSS_VM_IP="${VSS_VM_IP:-10.131.1.5}"

if curl -sf --max-time 15 http://localhost:8000/health | grep -q isAlive; then
  echo "agent ok (localhost:8000 -> ${VSS_VM_IP}:8000)"
else
  echo "agent unreachable - is the tunnel running? (tunnel.sh or start.sh)" >&2
  exit 1
fi

for port in 30081 30082; do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "http://localhost:${port}/v1/models" || echo 000)"
  echo "nim :${port} -> ${VSS_VM_IP}:${port}: HTTP ${code}"
done
