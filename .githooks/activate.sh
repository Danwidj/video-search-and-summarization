#!/bin/bash
# activate.sh: one-time setup per clone. .githooks/ is tracked and shared,
# but git only runs hooks from its configured hooks path, so every clone
# (laptop, VM, fresh worktree host) must run this once:
#
#   .githooks/activate.sh
#
# It is idempotent. The setting is local git config (per-clone, not
# committable), which is why this script exists - committing the hooks
# alone is not enough to make them fire.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
echo "activated: core.hooksPath=$(git config --get core.hooksPath)"
