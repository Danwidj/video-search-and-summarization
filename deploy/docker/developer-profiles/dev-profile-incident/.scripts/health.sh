#!/usr/bin/env bash
#
# Cross-profile deploy health check (replaces the old `mdx-health` shell
# alias from deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh — same behavior, standalone script).
#
# Every profile runs the agent and must answer on :8000/health
# (skills/vss-deploy-profile/references/readiness.md Step 2 "Cross-profile
# gate"; same probe listed per-profile in alerts.md).
#
# Through the tunnel this probes the VM's vss-agent via laptop-local
# localhost:8000; on the VM itself it probes the local :8000 directly.

curl -sf --max-time 15 http://localhost:8000/health && echo "agent ok"
