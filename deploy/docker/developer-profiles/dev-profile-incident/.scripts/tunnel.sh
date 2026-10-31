#!/usr/bin/env bash
#
# kwanz-ws backend tunnel — LAPTOP SIDE ONLY (replaces the old
# `mdx-tunnel-incident` shell alias from deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh — same
# behavior, standalone script).
#
# The laptop-local incident-console-v2 reaches the real kwanz-ws agent (:8000)
# through this SSH tunnel instead of the mock. Unlike every other script in
# this directory, this one runs on YOUR LAPTOP, not on the VM: it forwards a
# laptop-local port to the VM. Do not run it on kwanz-ws itself (forwarding
# the VM to itself is at best a no-op).
#
# Only :8000 is forwarded. The console uploads straight to R2, and the VM no
# longer runs VIOS/VST or the HAProxy ingress (:7777), so there is nothing else
# to reach (see .docs/decisions.md).
#
# Run this in the foreground (Ctrl-C closes it), then start the console
# locally against the tunneled agent. `start.sh` backgrounds the same tunnel
# automatically and cleans it up when the console exits.
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

ssh -N \
  -L 8000:127.0.0.1:8000 \
  "$VSS_SSH_TARGET"
