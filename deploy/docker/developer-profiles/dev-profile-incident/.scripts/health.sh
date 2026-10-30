#!/usr/bin/env bash
#
# Cross-profile deploy health check (replaces the old `mdx-health` shell
# alias from deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh — same behavior, standalone script).
#
# The mvp3 agent answers on :8001/health.
#
# Through the tunnel this probes the VM's vss-agent via laptop-local
# localhost:8001; on the VM itself it probes the local :8001 directly.

curl -sf --max-time 15 http://localhost:8001/health && echo "agent ok"
