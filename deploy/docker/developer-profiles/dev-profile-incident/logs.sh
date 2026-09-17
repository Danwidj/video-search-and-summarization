#!/usr/bin/env bash
#
# Tail logs for one container (default: vss-agent, the one service every
# profile runs). Replaces the old `mdx-logs` shell alias from
# deploy/dotfiles/aliases.sh — same behavior, standalone script.
#
# Pattern matches the per-service `docker logs <name>` calls documented
# throughout skills/vss-deploy-profile/references/*.md debugging sections
# (e.g. base.md: vss-vios-ingress, vss-vios-postgres; alerts.md:
# vss-rtvi-vlm, vss-alert-bridge).
#
# Usage: ./logs.sh [container-name]
# Runs on the VM against the local docker daemon.

docker logs -f --tail=100 "${1:-vss-agent}"
