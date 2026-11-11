#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermetic checks on env-file.sh (the VM env file name and the HOST_IP / VSS_APPS_DIR / VSS_DATA_DIR defaults)
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
# A stand-in `ip` gives the VM an address; bin_none gives it none.
mkdir -p "$TMP/bin" "$TMP/bin_none"
printf '#!/usr/bin/env bash\necho "1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.77 uid 0"\n' >"$TMP/bin/ip"
printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP/bin_none/ip"
chmod +x "$TMP/bin/ip" "$TMP/bin_none/ip"
export PATH="$TMP/bin:$PATH"
f="$profile/.env.remote"
run_defaults() { ( unset VSS_APPS_DIR VSS_DATA_DIR HOST_IP; "$@"; vm_env_defaults "$f" "$profile"; echo "apps=${VSS_APPS_DIR:-} data=${VSS_DATA_DIR:-}" ); }
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

# --- HOST_IP: blank or missing gets the VM's address, a filled-in value wins, no address fails ---
run_host() { ( unset HOST_IP; "$@"; vm_env_defaults "$f" "$profile"; echo "rc=$? host=${HOST_IP:-}" ); }
printf 'SECRET=keepme\n' >"$f";                check "missing HOST_IP is detected" "host=10.0.0.77" "$(run_host true)"
printf 'HOST_IP=\n' >"$f";                      check "blank HOST_IP is detected" "host=10.0.0.77" "$(run_host true)"
printf 'HOST_IP=10.9.9.9\n' >"$f";              check "a filled-in HOST_IP wins" "host=" "$(run_host true)"
printf 'HOST_IP=\n' >"$f";                      check "a caller's HOST_IP wins" "host=10.1.1.1" "$( ( export HOST_IP=10.1.1.1; vm_env_defaults "$f" "$profile"; echo "host=$HOST_IP" ) )"
printf 'HOST_IP=\n' >"$f"
out="$( ( PATH="$TMP/bin_none:$PATH"; unset HOST_IP; vm_env_defaults "$f" "$profile"; echo "rc=$?" ) 2>&1 )"
check "no address and a blank HOST_IP fails" "rc=1" "$out"
check "no address says why" "cannot determine this VM's address" "$out"
printf 'HOST_IP=10.9.9.9\n' >"$f"
check "a filled-in HOST_IP needs no address" "rc=0" "$( ( PATH="$TMP/bin_none:$PATH"; unset HOST_IP; vm_env_defaults "$f" "$profile"; echo "rc=$?" ) 2>&1 )"
[ "$(vm_host_ip)" = "10.0.0.77" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL vm_host_ip"; }
# The same pipeline runs inline in vm-ensure-docker.sh (it is piped over SSH and cannot source this file).
pipeline="$(sed -n '/^vm_host_ip()/,/^}/p' "$SCRIPT_DIR/env-file.sh" | sed -n '2p' | sed 's/^ *//')"
check "vm-ensure-docker.sh detects the address the same way" "$pipeline" "$(cat "$SCRIPT_DIR/vm-ensure-docker.sh")"

# --- vm_env_load: settings built from HOST_IP get the detected address, a filled-in value wins ---
printf 'HOST_IP=\nVSS_APPS_DIR=\nVSS_DATA_DIR=\nSECRET=keepme\nVST_INTERNAL_URL=http://${HOST_IP}:30888\n' >"$f"
out="$( ( unset HOST_IP VSS_APPS_DIR VSS_DATA_DIR; vm_env_load "$f" "$profile"; echo "url=$VST_INTERNAL_URL host=$HOST_IP data=$VSS_DATA_DIR secret=$SECRET" ) )"
check "built settings use the detected address" "url=http://10.0.0.77:30888 host=10.0.0.77 data=$root/.data secret=keepme" "$out"
printf 'HOST_IP=10.9.9.9\nVST_INTERNAL_URL=http://${HOST_IP}:30888\n' >"$f"
check "a filled-in HOST_IP wins in vm_env_load" "url=http://10.9.9.9:30888" "$( ( unset HOST_IP; vm_env_load "$f" "$profile"; echo "url=$VST_INTERNAL_URL" ) )"
check "vm_env_load fails when no address can be found" "rc=1" "$( ( PATH="$TMP/bin_none:$PATH"; unset HOST_IP; printf 'HOST_IP=\n' >"$f"; vm_env_load "$f" "$profile" 2>/dev/null; echo "rc=$?" ) )"

# --- the scripts use it, and no script still names only the old file ---
for s in native-services.sh rebuild-svc.sh tracking-stack.sh; do
  check "$s sources env-file.sh" 'source "${SCRIPT_DIR}/env-file.sh"' "$(cat "$SCRIPT_DIR/$s")"
done

echo "env-file: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
