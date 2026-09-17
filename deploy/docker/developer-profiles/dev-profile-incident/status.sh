#!/usr/bin/env bash
#
# Status check for the `mdx` compose project (replaces the old `mdx-ps`
# shell alias from deploy/dotfiles/aliases.sh — same behavior, standalone
# script).
#
# Direct `docker compose -p mdx ...` — stable, generic Compose surface, not
# project deploy-script surface, so no wrapper needed. It runs `cd` into
# deploy/docker in a subshell first: `compose.yml` (with its `include:` of
# services/developer-profiles/industry-profiles) only resolves via Compose's
# default discovery from that directory — dev-profile.sh's own state_up `cd`s
# there for the same reason before invoking `docker compose` —
# so running this from any other cwd (e.g. straight after login, from $HOME)
# would otherwise fail with "no configuration file provided". The subshell
# keeps the `cd` from changing the caller's actual shell directory.
#
# Runs on the VM against the local docker daemon (this is the laptop-side
# `start.sh` that brings everything up — start.sh runs its own SSH state
# check rather than calling this one).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

cd "$REPO_ROOT/deploy/docker" && docker compose -p mdx ps
