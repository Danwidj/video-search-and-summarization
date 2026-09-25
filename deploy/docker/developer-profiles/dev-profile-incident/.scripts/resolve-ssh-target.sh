#!/usr/bin/env bash
#
# Resolves VSS_SSH_TARGET (the "user@kwanz-ws" SSH login used by start.sh
# and tunnel.sh) without hardcoding or requiring an interactive prompt.
# SSH access to kwanz-ws is per-person — each teammate has their
# own account on the VM, configured via `Host kwanz-ws` in ~/.ssh/config
# (or overridden by VSS_SSH_USER / VSS_SSH_TARGET).
#
# Sourced (not executed) by start.sh / tunnel.sh, both of which already
# `set -u`/`set -e`-safe reference $VSS_SSH_TARGET afterward.
#
# Resolution order (non-interactive, no prompt ever):
#   1. VSS_SSH_TARGET already set (full "user@host" override) -> used as-is.
#   2. VSS_SSH_USER set -> used as the VM username.
#   3. ~/.ssh/config User for $VSS_SSH_HOST (via `ssh -G`).
#   4. Fall back to $USER / $(whoami).

VSS_SSH_HOST="${VSS_SSH_HOST:-kwanz-ws}"

if [ -z "${VSS_SSH_TARGET:-}" ]; then
  ssh_config_user="$(ssh -G "${VSS_SSH_HOST}" 2>/dev/null | awk '/^user / {print $2}' || true)"
  vm_user="${VSS_SSH_USER:-${ssh_config_user:-${USER:-$(whoami)}}}"
  VSS_SSH_TARGET="${vm_user}@${VSS_SSH_HOST}"
fi
