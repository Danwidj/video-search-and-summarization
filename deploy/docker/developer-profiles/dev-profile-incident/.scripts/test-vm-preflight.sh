#!/usr/bin/env bash
#
# Hermetic test for vm-preflight.sh (laptop side). A fake `ssh` and `tailscale`
# go first on PATH, so no network, VM or Tailscale is touched.
#   bash .scripts/test-vm-preflight.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
export PATH="$TMP/bin:$PATH"

# Fake ssh: FAKE_SSH_ERR -> print it and exit 255; FAKE_SSH_OUT -> print it; `-G` -> config dump.
cat >"$TMP/bin/ssh" <<'FAKE'
#!/usr/bin/env bash
if [ "$1" = "-G" ]; then echo "hostname vm-host.example.test"; echo "user daniel"; exit 0; fi
cat >/dev/null </dev/null 2>&1 || true
if [ -n "${FAKE_SSH_ERR:-}" ]; then echo "$FAKE_SSH_ERR" >&2; exit 255; fi
[ -n "${FAKE_SSH_SLEEP:-}" ] && sleep "$FAKE_SSH_SLEEP"
[ -n "${FAKE_SSH_OUT:-}" ] && echo "$FAKE_SSH_OUT"
exit 0
FAKE
# Fake tailscale: FAKE_TS_JSON is printed by `status --json`; FAKE_TS_DOWN=1 -> daemon error.
cat >"$TMP/bin/tailscale" <<'FAKE'
#!/usr/bin/env bash
[ -n "${FAKE_TS_DOWN:-}" ] && { echo "failed to connect to local tailscaled" >&2; exit 1; }
echo "$FAKE_TS_JSON"
FAKE
chmod +x "$TMP/bin/ssh" "$TMP/bin/tailscale"

export VSS_SSH_HOST=vm-host VSS_SSH_TARGET=daniel@vm-host
# shellcheck source=vm-preflight.sh
source "$SCRIPT_DIR/vm-preflight.sh"

pass=0 fail=0
check() { # check <name> <expected substring> <actual text>
  if grep -qF -- "$2" <<<"$3"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL $1: expected '$2' in:"; echo "$3" | sed 's/^/    /'; fi
}
run() { vm_preflight_ssh 2>&1; echo "rc=$?"; }
running='{"BackendState":"Running","Peer":{}}'

out="$(FAKE_TS_JSON=$running run)";                       check "reachable" "rc=0" "$out"
out="$(FAKE_SSH_ERR='ssh: Could not resolve hostname vm-host: nodename nor servname provided' FAKE_TS_JSON=$running run)"
check "dns" "does not resolve (DNS)" "$out"; check "dns rc" "rc=1" "$out"
out="$(FAKE_SSH_ERR='ssh: connect to host vm-host port 22: Operation timed out' FAKE_TS_JSON=$running run)"
check "timeout" "SSH timed out" "$out"; check "timeout hint" "tailscale ping" "$out"
out="$(FAKE_SSH_ERR='ssh: connect to host vm-host port 22: Connection refused' FAKE_TS_JSON=$running run)"
check "refused" "SSH server is not running" "$out"
out="$(FAKE_SSH_ERR='ssh: connect to host vm-host port 22: No route to host' FAKE_TS_JSON=$running run)"
check "no route" "no network route" "$out"
out="$(FAKE_SSH_ERR='daniel@vm-host: Permission denied (publickey).' FAKE_TS_JSON=$running run)"
check "auth" "rejected the login" "$out"
out="$(FAKE_SSH_ERR='Host key verification failed.' FAKE_TS_JSON=$running run)"
check "hostkey" "ssh-keygen -R" "$out"
out="$(FAKE_SSH_ERR='ssh: Could not resolve hostname vm-host' FAKE_TS_JSON='{"BackendState":"NeedsLogin"}' run)"
check "ts login" "Tailscale is not logged in" "$out"
out="$(FAKE_SSH_ERR='Operation timed out' FAKE_TS_JSON='{"BackendState":"Stopped"}' run)"
check "ts stopped" "installed but not running" "$out"
out="$(FAKE_SSH_ERR='ssh: Could not resolve hostname vm-host' FAKE_TS_DOWN=1 run)"
check "ts daemon" "Tailscale daemon is not running" "$out"
out="$(FAKE_SSH_ERR='Operation timed out' FAKE_TS_JSON='{"BackendState":"Running","Peer":{"a":{"HostName":"vm-host","DNSName":"vm-host.example.test.","Online":false,"LastSeen":"2026-10-18T01:00:00Z"}}}' run)"
check "peer offline" "OFFLINE in the tailnet" "$out"; check "peer lastseen" "2026-10-18T01:00:00Z" "$out"

# vm_detect_ip: override wins; detection parses the route; failure falls back.
export VSS_VM_IP=1.2.3.4; check "ip override" "1.2.3.4" "$(vm_detect_ip 2>/dev/null)"
unset VSS_VM_IP
out="$(FAKE_SSH_OUT='1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.77 uid 1000' vm_detect_ip 2>/dev/null)"; check "ip detect" "10.0.0.77" "$out"
out="$(FAKE_SSH_ERR='boom' vm_detect_ip 2>/dev/null)"; check "ip fallback" "<vm-ip>" "$out"

# The merged helper resolves the SSH target when callers do not provide one.
unset VSS_SSH_TARGET VSS_SSH_USER
source "$SCRIPT_DIR/vm-preflight.sh"
check "ssh config target" "daniel@vm-host" "$VSS_SSH_TARGET"
VSS_SSH_USER=alice
unset VSS_SSH_TARGET
source "$SCRIPT_DIR/vm-preflight.sh"
check "ssh user target" "alice@vm-host" "$VSS_SSH_TARGET"
VSS_SSH_TARGET=carol@custom-host
source "$SCRIPT_DIR/vm-preflight.sh"
check "explicit target" "carol@custom-host" "$VSS_SSH_TARGET"

# vm_ssh_limited: passes stdin through, returns ssh's exit code, enforces the limit.
out="$(echo hi | vm_ssh_limited 5 host cmd; echo "rc=$?")"; check "limited ok" "rc=0" "$out"
SECONDS=0; FAKE_SSH_SLEEP=30 vm_ssh_limited 2 host cmd; rc=$?
check "limited kills" "143" "$rc"; [ "$SECONDS" -lt 10 ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL limited took ${SECONDS}s"; }

# No built-in host: unset VSS_SSH_HOST (and no .env.local key) stops with a one-line message naming it.
# A copy of the scripts in a temp profile dir keeps the real .env.local out of the test.
mkdir -p "$TMP/profile/.scripts"
cp "$SCRIPT_DIR/vm-host.sh" "$SCRIPT_DIR/vm-preflight.sh" "$TMP/profile/.scripts/"
out="$(env -u VSS_SSH_HOST -u VSS_SSH_TARGET bash -c 'source "$1"; echo reached' _ "$TMP/profile/.scripts/vm-preflight.sh" 2>&1)"
check "host unset" "VSS_SSH_HOST is not set" "$out"
[[ "$out" != *reached* ]] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL host unset: script went on"; }
# .env.local supplies the host (only that key is read; other lines are ignored, never executed).
printf 'OTHER=$(touch "%s/ran")\nVSS_SSH_HOST="from-env-local" # note\n' "$TMP" >"$TMP/profile/.env.local"
out="$(env -u VSS_SSH_HOST -u VSS_SSH_TARGET -u VSS_SSH_USER bash -c 'source "$1"; echo "$VSS_SSH_HOST"' _ "$TMP/profile/.scripts/vm-preflight.sh" 2>&1)"
check ".env.local host" "from-env-local" "$out"; [ ! -e "$TMP/ran" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL .env.local was executed"; }
out="$(VSS_SSH_HOST=from-env env -u VSS_SSH_TARGET bash -c 'source "$1"; echo "$VSS_SSH_HOST"' _ "$TMP/profile/.scripts/vm-preflight.sh" 2>&1)"
check "env beats .env.local" "from-env" "$out"

# The on-the-VM guard compares the local short hostname with the configured host's short name.
printf '#!/bin/sh\necho local-vm\n' >"$TMP/bin/hostname"; chmod +x "$TMP/bin/hostname"
VSS_SSH_HOST=local-vm.example.test vm_running_on_host && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL guard: same short name"; }
VSS_SSH_HOST=other-host vm_running_on_host && { fail=$((fail + 1)); echo "FAIL guard: other host"; } || pass=$((pass + 1))
VSS_SSH_HOST='' vm_running_on_host && { fail=$((fail + 1)); echo "FAIL guard: unset host"; } || pass=$((pass + 1))

echo "vm-preflight: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
