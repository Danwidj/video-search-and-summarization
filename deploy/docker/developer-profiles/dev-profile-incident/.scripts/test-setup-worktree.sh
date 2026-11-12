#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermetic checks on .githooks/setup-worktree.sh Part 0 and Part B, in a throwaway git repo:
# a VM-shaped checkout (.env.remote, no .env.local) gets no .env.local and no links; a laptop-shaped
# one (.env.local present, or neither file) is set up as before. No Docker, no VM, no real env file.
#   bash .scripts/test-setup-worktree.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$(cd "$SCRIPT_DIR/../../../../.." && pwd)/.githooks/setup-worktree.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0 fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL $1"; }
[ -f "$HOOK" ] || { echo "FAIL hook not found: $HOOK"; exit 1; }

REL="deploy/docker/developer-profiles/dev-profile-incident"
SUBS="incident-console-v2 vlm-gateway mock-backend"

# new_checkout <name> <files...>: a git repo whose profile folder holds the template .env plus the named files.
new_checkout() {
  local d="$TMP/$1"; shift
  mkdir -p "$d/$REL" "$d/$REL/incident-console-v2" "$d/$REL/vlm-gateway" "$d/$REL/mock-backend"
  git -C "$d" init -q
  printf 'SETTING=\n' >"$d/$REL/.env"
  local f
  for f in "$@"; do printf 'PLACEHOLDER=\n' >"$d/$REL/$f"; done
  echo "$d"
}
run_hook() { ( cd "$1" && bash "$HOOK" 2>&1 ); }
has_links() { local s; for s in $SUBS; do [ -L "$1/$REL/$s/.env.local" ] || return 1; done; }
no_links() { local s; for s in $SUBS; do [ ! -e "$1/$REL/$s/.env.local" ] && [ ! -L "$1/$REL/$s/.env.local" ] || return 1; done; }

# --- VM-shaped: .env.remote and no .env.local ---
d="$(new_checkout vm .env.remote)"
out="$(run_hook "$d")"
{ [ ! -e "$d/$REL/.env.local" ] && [ ! -L "$d/$REL/.env.local" ]; } && ok || bad "VM checkout must not get a .env.local"
no_links "$d" && ok || bad "VM checkout must not get the per-service links"
[ -z "$out" ] && ok || bad "VM checkout must be silent, got: $out"
run_hook "$d" >/dev/null
[ ! -e "$d/$REL/.env.local" ] && ok || bad "a second run must not create .env.local either"
[ "$(cat "$d/$REL/.env.remote")" = "PLACEHOLDER=" ] && ok || bad "the hook must not touch .env.remote"

# --- laptop-shaped, neither file: seeded from the template, links made ---
d="$(new_checkout laptop-fresh)"
out="$(run_hook "$d")"
cmp -s "$d/$REL/.env" "$d/$REL/.env.local" && ok || bad "a fresh laptop checkout must be seeded from .env"
grep -qF "seeded" <<<"$out" && ok || bad "seeding must be logged, got: $out"
has_links "$d" && ok || bad "a fresh laptop checkout must get the per-service links"
[ "$(readlink "$d/$REL/vlm-gateway/.env.local")" = "../.env.local" ] && ok || bad "links must point at ../.env.local"

# --- laptop-shaped, .env.local present (even with a .env.remote beside it): kept, links made ---
d="$(new_checkout laptop-existing .env.local .env.remote)"
run_hook "$d" >/dev/null
[ "$(cat "$d/$REL/.env.local")" = "PLACEHOLDER=" ] && ok || bad "an existing .env.local must be left alone"
has_links "$d" && ok || bad "a checkout with .env.local must get the per-service links"

# --- laptop-shaped, broken link: repaired ---
d="$(new_checkout laptop-heal .env.local)"

printf 'x\n' >"$d/$REL/vlm-gateway/.env.local"
run_hook "$d" >/dev/null
[ "$(readlink "$d/$REL/vlm-gateway/.env.local")" = "../.env.local" ] && ok || bad "a real file in place of a link must be replaced"

# --- VM-shaped: a stray non-link is not repaired either ---
d="$(new_checkout vm-stray .env.remote)"

printf 'x\n' >"$d/$REL/vlm-gateway/.env.local"
run_hook "$d" >/dev/null
[ ! -L "$d/$REL/vlm-gateway/.env.local" ] && ok || bad "VM checkout must not repair links"

echo "test-setup-worktree: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
