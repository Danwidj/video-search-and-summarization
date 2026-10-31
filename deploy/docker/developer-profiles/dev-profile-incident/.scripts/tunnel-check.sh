#!/usr/bin/env bash
#
# Prove the tunnel is up from the laptop end (replaces the old
# `mdx-tunnel-incident-check` shell alias from deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh —
# same behavior, standalone script). LAPTOP SIDE ONLY, like tunnel.sh.
#
# The agent health check must pass. Only :8000 is forwarded: the VM no longer
# runs the VIOS/VST HAProxy ingress (:7777).

if curl -sf --max-time 15 http://localhost:8000/health | grep -q isAlive; then
  echo "agent ok (localhost:8000 -> VM loopback :8000)"
else
  echo "agent unreachable - is the tunnel running? (tunnel.sh or start.sh)" >&2
  exit 1
fi

search_code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -X POST http://localhost:8000/api/v1/incidents/search -H "Content-Type: application/json" -d '{"query":"healthcheck","top_k":1}' || echo 000)"
if [ "$search_code" = "200" ]; then
  echo "search route ok (localhost:8000/api/v1/incidents/search -> VM loopback :8000)"
else
  echo "search route returned HTTP ${search_code} (expected 200)"
fi
