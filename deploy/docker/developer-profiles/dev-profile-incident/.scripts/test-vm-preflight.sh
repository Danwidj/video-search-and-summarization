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
if [ "$1" = "-G" ]; then echo "hostname kwanz-ws.tailnet.ts.net"; echo "user daniel"; exit 0; fi
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

export VSS_SSH_HOST=kwanz-ws VSS_SSH_TARGET=daniel@kwanz-ws
# shellcheck source=vm-preflight.sh
source "$SCRIPT_DIR/vm-preflight.sh"

pass=0 fail=0
check() { # check <name> <expected substring> <actual text>
  if grep -qF -- "$2" <<<"$3"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL $1: expected '$2' in:"; echo "$3" | sed 's/^/    /'; fi
}
run() { vm_preflight_ssh 2>&1; echo "rc=$?"; }
running='{"BackendState":"Running","Peer":{}}'

out="$(FAKE_TS_JSON=$running run)";                       check "reachable" "rc=0" "$out"
out="$(FAKE_SSH_ERR='ssh: Could not resolve hostname kwanz-ws: nodename nor servname provided' FAKE_TS_JSON=$running run)"
check "dns" "does not resolve (DNS)" "$out"; check "dns rc" "rc=1" "$out"
out="$(FAKE_SSH_ERR='ssh: connect to host kwanz-ws port 22: Operation timed out' FAKE_TS_JSON=$running run)"
check "timeout" "SSH timed out" "$out"; check "timeout hint" "tailscale ping" "$out"
out="$(FAKE_SSH_ERR='ssh: connect to host kwanz-ws port 22: Connection refused' FAKE_TS_JSON=$running run)"
check "refused" "SSH server is not running" "$out"
out="$(FAKE_SSH_ERR='ssh: connect to host kwanz-ws port 22: No route to host' FAKE_TS_JSON=$running run)"
check "no route" "no network route" "$out"
out="$(FAKE_SSH_ERR='daniel@kwanz-ws: Permission denied (publickey).' FAKE_TS_JSON=$running run)"
check "auth" "rejected the login" "$out"
out="$(FAKE_SSH_ERR='Host key verification failed.' FAKE_TS_JSON=$running run)"
check "hostkey" "ssh-keygen -R" "$out"
out="$(FAKE_SSH_ERR='ssh: Could not resolve hostname kwanz-ws' FAKE_TS_JSON='{"BackendState":"NeedsLogin"}' run)"
check "ts login" "Tailscale is not logged in" "$out"
out="$(FAKE_SSH_ERR='Operation timed out' FAKE_TS_JSON='{"BackendState":"Stopped"}' run)"
check "ts stopped" "installed but not running" "$out"
out="$(FAKE_SSH_ERR='ssh: Could not resolve hostname kwanz-ws' FAKE_TS_DOWN=1 run)"
check "ts daemon" "Tailscale daemon is not running" "$out"
out="$(FAKE_SSH_ERR='Operation timed out' FAKE_TS_JSON='{"BackendState":"Running","Peer":{"a":{"HostName":"kwanz-ws","DNSName":"kwanz-ws.tailnet.ts.net.","Online":false,"LastSeen":"2026-10-18T01:00:00Z"}}}' run)"
check "peer offline" "OFFLINE in the tailnet" "$out"; check "peer lastseen" "2026-10-18T01:00:00Z" "$out"

# vm_detect_ip: override wins; detection parses the route; failure falls back.
export VSS_VM_IP=1.2.3.4; check "ip override" "1.2.3.4" "$(vm_detect_ip 2>/dev/null)"
unset VSS_VM_IP
out="$(FAKE_SSH_OUT='1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.77 uid 1000' vm_detect_ip 2>/dev/null)"; check "ip detect" "10.0.0.77" "$out"
out="$(FAKE_SSH_ERR='boom' vm_detect_ip 2>/dev/null)"; check "ip fallback" "10.131.1.5" "$out"

# vm_ssh_limited: passes stdin through, returns ssh's exit code, enforces the limit.
out="$(echo hi | vm_ssh_limited 5 host cmd; echo "rc=$?")"; check "limited ok" "rc=0" "$out"
SECONDS=0; FAKE_SSH_SLEEP=30 vm_ssh_limited 2 host cmd; rc=$?
check "limited kills" "143" "$rc"; [ "$SECONDS" -lt 10 ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL limited took ${SECONDS}s"; }

echo "vm-preflight: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
