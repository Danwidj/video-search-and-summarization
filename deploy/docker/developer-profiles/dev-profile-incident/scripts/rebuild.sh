#!/usr/bin/env bash
#
# Full profile rebuild/redeploy — thin wrapper around the project's own
# canonical deploy script (deploy/docker/scripts/dev-profile.sh), not a
# hand-rolled docker/compose invocation, because THE DEPLOY COMMAND WILL
# CHANGE OVER TIME: when dev-profile.sh's flags change, only this one
# wrapper needs updating, not everyone's muscle memory.
#
# `dev-profile.sh up --profile <base|search|lvs|alerts> ...` already runs
# `docker compose up --detach --force-recreate --build` internally, so this
# IS the project's rebuild/reinstall-image command — see
# deploy/docker/scripts/dev-profile.sh (state_up/state_down) and the
# worked examples in docs/incident-plan/incident-plan-overview.md.
#
# NOTE: dev-profile.sh has NO `incident` profile — this rebuilds the stock
# profiles (base/search/lvs/alerts). The incident profile never goes through
# dev-profile.sh; its deploy is the direct compose invocation in start.sh
# (see docs/incident-plan/incident-plan-implementation-remote.md §2).
#
# WARNING (grounded in dev-profile.sh's own state_down, run internally
# before every `up`): this tears the existing stack down WITH -v and
# deletes the whole data directory first — same ~35GB-cache-loss behavior
# down.sh exists to avoid. There is no "rebuild images only" mode in the
# script today; this wrapper does not invent one, it just says so loudly.
#
# Replaces the old `mdx-rebuild` shell function from
# deploy/dotfiles/aliases.sh — same behavior (incl. the explicit
# confirmation prompt), standalone script. Runs on the VM.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

if [ -z "$1" ]; then
  echo "usage: rebuild.sh --profile <base|search|lvs|alerts> [dev-profile.sh options...]" >&2
  echo "  (see: $REPO_ROOT/deploy/docker/scripts/dev-profile.sh --help)" >&2
  exit 1
fi

echo "rebuild.sh: dev-profile.sh up tears down the stack WITH -v (wipes the" >&2
echo "model-weight cache) before rebuilding — see this script's header comment." >&2
# Explicit prompt, not a "Ctrl-C to abort" countdown: a Ctrl-C during a
# plain `sleep` doesn't reliably abort the rest of a shell function (the
# sleep's own interrupted exit status was never even checked here), so a
# would-be abort could silently fall through into the destructive `up`.
read -r -p "Proceed and wipe the model-weight cache? [y/N] " _confirm
case "$_confirm" in
  y|Y|yes|YES) ;;
  *) echo "rebuild.sh: aborted." >&2; exit 1 ;;
esac

"$REPO_ROOT/deploy/docker/scripts/dev-profile.sh" up "$@"
