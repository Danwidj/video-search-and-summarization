#!/usr/bin/env bash
#
# kwanz-ws backend tunnel — LAPTOP SIDE ONLY (replaces the old
# `mdx-tunnel-incident` shell alias from deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh — same
# behavior, standalone script).
#
# The laptop-local incident-console-v2 reaches the real kwanz-ws backend (agent
# :8000, ingress :7777) through this SSH tunnel instead of the mock
# (see deploy/docker/developer-profiles/dev-profile-incident/dotfiles/README.md). Phase 4 design: the console never deploys
# to the VM; the VM runs only the backend stack. Unlike every other script
# in this directory, this one runs on YOUR LAPTOP, not on the VM: it
# forwards laptop-local ports to the VM's backend. Do not run it on
# kwanz-ws itself (forwarding the VM to itself is at best a no-op).
#
# Same tunnel pattern as the base-profile VSS UI tunnel in
# ../README.md:
# `ssh -N -L 7777:10.131.1.5:7777 daniel@kwanz-ws`.
#
# Forwarded ports mirror the backend's real ports one-to-one
# (dev-profile-base/.env: VSS_AGENT_PORT=8000; dev-profile-incident/.env:
# HAPROXY_PORT=7777), so the usual laptop-side URLs keep working unchanged
# through the tunnel: http://localhost:8000/health for the agent health check
# (see dev-profile-incident/.env INCIDENT_AGENT_BASE_URL) and http://localhost:7777
# for the ingress proxy. The VM address is detected over SSH (default-route source
# address); set VSS_VM_IP / VSS_SSH_TARGET only to force a different address or login.
#
# Run this in the foreground (Ctrl-C closes it). Run it first, then start
# the console locally against the tunneled backend. The `start.sh` wrapper
# backgrounds a tunnel with the same forwards automatically and cleans it up
# when the console exits.
#
# VM username resolution (VSS_SSH_TARGET / VSS_SSH_USER / VSS_SSH_HOST) is
# non-interactive (no prompt) — see vm-preflight.sh for the full order.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=vm-preflight.sh
source "${SCRIPT_DIR}/vm-preflight.sh"

if [ "$(hostname -s 2>/dev/null)" = "kwanz-ws" ]; then
  echo "tunnel.sh: run this from your laptop, not on kwanz-ws (it forwards laptop ports to the VM)." >&2
  exit 1
fi

vm_preflight_ssh || exit 1
VSS_VM_IP="$(vm_detect_ip)"

ssh -N \
  -L 8000:127.0.0.1:8000 \
  -L 7777:"$VSS_VM_IP":7777 \
  "$VSS_SSH_TARGET"
