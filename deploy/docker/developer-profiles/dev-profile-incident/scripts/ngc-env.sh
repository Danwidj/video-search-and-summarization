#!/usr/bin/env bash
#
# Source the shared NVIDIA/NGC credential file into the current shell
# (replaces the old `ngc-env-on` shell function from
# deploy/docker/developer-profiles/dev-profile-incident/dotfiles/aliases.sh — same behavior, standalone script).
#
# /srv/rise-up/.ngc_env is a shared NVIDIA/NGC credential file for the whole
# smu-rise-up group's single checkout — auto-sourcing it into every login
# shell would silently export a shared credential the moment anyone runs
# this bootstrap. Call this when you actually need it.
#
# Run as `source ./ngc-env.sh` or `. ./ngc-env.sh` — as a script it can only
# set the credentials in the short-lived subshell it runs in, which is
# useless. (Plain `source` only sets shell variables in *this* shell — it
# does not export them, so dev-profile.sh/NGC tooling run as a child process
# would still see no credential. `set -a`/`set +a` here is this repo's own
# documented way to source it, from
# ../README.md; save/restore any prior
# allexport state rather than assuming it was off.)

ngc_env="${VSS_NGC_ENV:-/srv/rise-up/.ngc_env}"
if [ -f "$ngc_env" ]; then
  _had_allexport=0
  case "$-" in *a*) _had_allexport=1 ;; esac
  set -a
  # shellcheck disable=SC1090
  source "$ngc_env"
  [ "$_had_allexport" -eq 1 ] || set +a
  echo "ngc-env.sh: sourced $ngc_env (exported)"
else
  echo "ngc-env.sh: $ngc_env not found (set VSS_NGC_ENV to override)" >&2
  return 1
fi
