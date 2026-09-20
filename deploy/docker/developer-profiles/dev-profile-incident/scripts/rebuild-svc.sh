#!/usr/bin/env bash
#
# Fast single-service rebuild (no full stack teardown/redeploy). Replaces the
# old `mdx-rebuild-svc` shell function from deploy/dotfiles/aliases.sh — same
# behavior, standalone script.
#
# Direct compose invocation — documented pattern, not a dev-profile.sh flag:
# docs/incident-plan/incident-plan-implementation-local.md and -remote.md
# both call out `docker compose up -d --build vss-agent` for a quick agent
# rebuild and `docker compose up -d --force-recreate <vios-service>` for
# VIOS (no in-container dev-server mode for either).
#
# Unlike status.sh/down.sh, this actually recreates containers, so it needs
# the currently-up profile's real config (image tags, device IDs, ...) —
# not just the project label. `dev-profile.sh up` writes exactly one
# developer-profiles/dev-profile-*/generated.env at a time (state_down
# deletes all of them first), so whichever one exists is the active
# profile; same `cd`-into-deploy/docker reasoning as status.sh for resolving
# compose.yml's `include:`. The incident profile's hand-made env is
# `dev-profile-incident/generated.env.<local|remote>` (dev-profile.sh has no
# incident profile — see docs/incident-plan/incident-plan-implementation-remote.md
# §2), so the glob below matches those too.
#
# Runs on the VM against the local docker daemon.
#
# Usage: ./rebuild-svc.sh <service> [more services...]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

if [ -z "$1" ]; then
  echo "usage: rebuild-svc.sh <service> [more services...]" >&2
  exit 1
fi

compose_dir="$REPO_ROOT/deploy/docker"
generated_env="$(command ls "$compose_dir"/developer-profiles/dev-profile-*/generated.env* 2>/dev/null | head -1)"
if [ -z "$generated_env" ]; then
  echo "rebuild-svc.sh: no active profile found (no generated.env under" >&2
  echo "  $compose_dir/developer-profiles/) — is a profile currently up via dev-profile.sh?" >&2
  exit 1
fi

cd "$compose_dir" && docker compose --env-file "$generated_env" -p mdx up -d --build --force-recreate "$@"
