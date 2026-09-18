#!/usr/bin/env bash
#
# Resolves VSS_SSH_TARGET (the "user@kwanz-ws" SSH login used by start.sh
# and tunnel.sh) without hardcoding or requiring a manually-edited VM
# username. SSH access to kwanz-ws is per-person — each teammate has their
# own account on the VM, which does not always match their local shell
# username — so this picks a sensible default and confirms it rather than
# silently assuming local == VM username.
#
# Sourced (not executed) by start.sh / tunnel.sh, both of which already
# `set -u`/`set -e`-safe reference $VSS_SSH_TARGET afterward.
#
# Resolution order:
#   1. VSS_SSH_TARGET already set (full "user@host" override) -> used as-is,
#      no prompt. Covers any existing scripted/automated use of start.sh.
#   2. VSS_SSH_USER set -> used as the VM username, no prompt (the
#      non-interactive override for just the username).
#   3. Interactive terminal -> prompt for the VM username, pre-filled with
#      $USER/$(whoami) as the default (Enter accepts it).
#   4. Non-interactive with neither override set -> fall back to
#      $USER/$(whoami) silently (e.g. cron/CI use of these scripts).

VSS_SSH_HOST="${VSS_SSH_HOST:-kwanz-ws}"

if [ -z "${VSS_SSH_TARGET:-}" ]; then
  default_vm_user="${USER:-$(whoami)}"
  if [ -n "${VSS_SSH_USER:-}" ]; then
    vm_user="$VSS_SSH_USER"
  elif [ -t 0 ]; then
    read -r -p "VM SSH username for ${VSS_SSH_HOST} [${default_vm_user}]: " vm_user
    vm_user="${vm_user:-$default_vm_user}"
  else
    vm_user="$default_vm_user"
  fi
  VSS_SSH_TARGET="${vm_user}@${VSS_SSH_HOST}"
fi
