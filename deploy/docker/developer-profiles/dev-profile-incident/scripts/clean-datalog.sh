#!/usr/bin/env bash
#
# On-disk data-dir cleanup between deploys/profile switches — thin wrapper
# around the project's own cleanup script (not a hand-rolled rm -rf), same
# "deploy command changes over time" reasoning as rebuild.sh. Resolves
# generated.env (falling back to .env pre-first-deploy) exactly as
# documented in skills/vss-deploy-profile/references/teardown.md Step 0b,
# and requires passwordless sudo per that doc's gate (never runs privileged
# cleanup any other way).
#
# Replaces the old `mdx-clean-datalog` shell function from
# deploy/dotfiles/aliases.sh — same behavior, standalone script.
# Runs on the VM.
#
# Usage: ./clean-datalog.sh <base|search|lvs|alerts>

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

profile="$1"
case "$profile" in
  base|search|lvs|alerts) ;;
  *)
    echo "usage: clean-datalog.sh <base|search|lvs|alerts>" >&2
    exit 1
    ;;
esac

profile_dir="$REPO_ROOT/deploy/docker/developer-profiles/dev-profile-${profile}"
env_file="$profile_dir/generated.env"
[ -f "$env_file" ] || env_file="$profile_dir/.env"
if [ ! -f "$env_file" ]; then
  echo "clean-datalog.sh: no env file found under $profile_dir" >&2
  exit 1
fi

if sudo -n true 2>/dev/null; then
  sudo bash "$REPO_ROOT/deploy/docker/scripts/cleanup_all_datalog.sh" --env-file "$env_file"
else
  echo "clean-datalog.sh: sudo needs a password — run this once yourself:" >&2
  echo "  sudo bash $REPO_ROOT/deploy/docker/scripts/cleanup_all_datalog.sh --env-file $env_file" >&2
  exit 1
fi
