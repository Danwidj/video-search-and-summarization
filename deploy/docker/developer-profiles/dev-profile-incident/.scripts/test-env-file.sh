#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermetic checks on env-file.sh (the VM env file name and the VSS_APPS_DIR / VSS_DATA_DIR defaults)
# and on the scripts that use it. No Docker, no VM.
#   bash .scripts/test-env-file.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass=0 fail=0
check() { if grep -qF -- "$2" <<<"$3"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL $1: expected '$2' in: $3"; fi; }
check_not() { if grep -qF -- "$2" <<<"$3"; then fail=$((fail + 1)); echo "FAIL $1: '$2' must not be in: $3"; else pass=$((pass + 1)); fi; }

# A fake checkout: <root>/deploy/docker/developer-profiles/dev-profile-incident
root="$TMP/vss"
profile="$root/deploy/docker/developer-profiles/dev-profile-incident"
mkdir -p "$profile"
# shellcheck source=env-file.sh
source "$SCRIPT_DIR/env-file.sh"

# --- env file name ---
check "no file" "" "$(vm_env_file "$profile")"
[ -z "$(vm_env_file "$profile")" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL no env file must print nothing"; }
: >"$profile/generated.env.remote"
check "old name alone" "$profile/generated.env.remote" "$(vm_env_file "$profile" 2>&1)"
: >"$profile/.env.remote"
out="$(vm_env_file "$profile" 2>&1)"
check "new name wins" "$profile/.env.remote" "$out"
check "both names say so" "both .env.remote and generated.env.remote exist" "$out"
rm "$profile/generated.env.remote"
check_not "new name alone is quiet" "both" "$(vm_env_file "$profile" 2>&1)"

# --- defaults ---
f="$profile/.env.remote"
run_defaults() { ( unset VSS_APPS_DIR VSS_DATA_DIR; "$@"; vm_env_defaults "$f" "$profile"; echo "apps=${VSS_APPS_DIR:-} data=${VSS_DATA_DIR:-}" ); }
printf 'SECRET=keepme\n' >"$f"
check "missing keys get defaults" "apps=$root/deploy/docker data=$root/.data" "$(run_defaults true)"
printf 'VSS_APPS_DIR=\nVSS_DATA_DIR=\n' >"$f"
check "blank keys get defaults" "apps=$root/deploy/docker data=$root/.data" "$(run_defaults true)"
printf 'VSS_APPS_DIR="/opt/apps"\nVSS_DATA_DIR=/mnt/data # note\n' >"$f"
check "filled keys win" "apps= data=" "$(run_defaults true)"
printf 'VSS_APPS_DIR=\nVSS_DATA_DIR=\n' >"$f"
check "a caller's value wins" "apps=/caller data=$root/.data" "$( ( unset VSS_DATA_DIR; export VSS_APPS_DIR=/caller; vm_env_defaults "$f" "$profile"; echo "apps=$VSS_APPS_DIR data=$VSS_DATA_DIR" ) )"
[ ! -e "$root/.data" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL defaults must not create the data directory"; }
check "the file is untouched" "VSS_DATA_DIR=" "$(cat "$f")"

# --- the scripts use it, and no script still names only the old file ---
for s in native-services.sh rebuild-svc.sh tracking-stack.sh; do
  check "$s sources env-file.sh" 'source "${SCRIPT_DIR}/env-file.sh"' "$(cat "$SCRIPT_DIR/$s")"
done

echo "env-file: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
