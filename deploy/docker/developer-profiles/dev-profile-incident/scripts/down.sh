#!/usr/bin/env bash
#
# Stop the `mdx` compose stack WITHOUT wiping the model-weight cache
# (replaces the old `mdx-down` shell alias from deploy/dotfiles/aliases.sh —
# same behavior, standalone script).
#
# Deliberately never `-v`: dev-profile.sh's own `down` runs
# `docker compose -p mdx down -v --remove-orphans` and then deletes the whole
# data directory, which is exactly the ~35GB-of-NIM/RTVI-cache-loss behavior
# this project's own docs tell you to avoid — see
# docs/incident-plan/incident-plan-overview.md ("Never run
# `dev-profile.sh down`") and skills/vss-deploy-profile/references/teardown.md's
# cache-preserving teardown, whose exact
# `docker compose -p mdx down --remove-orphans` this mirrors. Direct compose
# invocation, not a dev-profile.sh wrapper, precisely because the safe
# behavior here means NOT calling dev-profile.sh's `down`.
#
# Same subshell-`cd` reasoning as status.sh (compose.yml only resolves via
# Compose's default discovery from deploy/docker).
#
# Runs on the VM against the local docker daemon.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"

cd "$REPO_ROOT/deploy/docker" && docker compose -p mdx down --remove-orphans
