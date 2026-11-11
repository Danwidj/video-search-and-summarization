#!/usr/bin/env bash
#
# vm-host.sh — LAPTOP SIDE ONLY. Sourced by start.sh, tunnel.sh and vm-preflight.sh.
#
# The VM host has no built-in default. It comes from VSS_SSH_HOST in the
# environment, else from the VSS_SSH_HOST line of the profile's .env.local.
# Only that one key is read from .env.local: the file is never sourced or printed.
#
#   vm_load_ssh_host <caller>     set VSS_SSH_HOST from .env.local when the environment lacks it
#   vm_require_ssh_host <caller>  vm_load_ssh_host, then fail with a one-line message when still unset
#   vm_running_on_host            true when this machine is the configured VM host

_VM_HOST_PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

vm_load_ssh_host() {
  if [ -z "${VSS_SSH_HOST:-}" ] && [ -f "${_VM_HOST_PROFILE_DIR}/.env.local" ]; then
    VSS_SSH_HOST="$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?VSS_SSH_HOST=[[:space:]]*//p' "${_VM_HOST_PROFILE_DIR}/.env.local" \
      | tail -n 1 | sed -E "s/[[:space:]]+#.*$//; s/^[\"']//; s/[\"'][[:space:]]*$//")"
  fi
  [ -n "${VSS_SSH_HOST:-}" ] && export VSS_SSH_HOST
  return 0
}

vm_require_ssh_host() {
  vm_load_ssh_host
  if [ -z "${VSS_SSH_HOST:-}" ]; then
    echo "${1:-vm-host.sh}: VSS_SSH_HOST is not set; set it to the VM hostname in the environment or in ${_VM_HOST_PROFILE_DIR}/.env.local." >&2
    return 1
  fi
}

# Compares the local short hostname with the short name of VSS_SSH_HOST and of
# the hostname ~/.ssh/config maps it to. False when VSS_SSH_HOST is unset.
vm_running_on_host() {
  local local_host candidate resolved
  [ -n "${VSS_SSH_HOST:-}" ] || return 1
  local_host="$(hostname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  [ -n "$local_host" ] || return 1
  resolved="$(ssh -G "$VSS_SSH_HOST" 2>/dev/null | awk '/^hostname / {print $2; exit}' || true)"
  for candidate in "$VSS_SSH_HOST" "$resolved"; do
    candidate="$(printf '%s' "${candidate%%.*}" | tr '[:upper:]' '[:lower:]')"
    [ -n "$candidate" ] && [ "$candidate" = "$local_host" ] && return 0
  done
  return 1
}
