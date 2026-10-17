#!/usr/bin/env bash
#
# Hermetic test for vm-ensure-docker.sh (the VM-side step start.sh pipes over SSH).
# Fake `docker`, `ip` and `timeout` stand in for the VM.
#   bash .scripts/test-vm-ensure-docker.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$SCRIPT_DIR/vm-ensure-docker.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
export PATH="$TMP/bin:$PATH"

# Fake docker: behaviour switched by FAKE_* env vars; every call is logged to $TMP/docker.log.
cat >"$TMP/bin/docker" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_LOG"
case "$1" in
  info) [ -z "${FAKE_DOCKER_DOWN:-}" ] ;;
  image) [ -z "${FAKE_MISSING_IMAGE:-}" ] ;;
  compose)
    for a in "$@"; do
      case "$a" in
        config) echo "redis:8"; exit 0 ;;
        pull) [ -n "${FAKE_PULL_FAIL:-}" ] && { echo "unauthorized: authentication required" >&2; exit 1; }; exit 0 ;;
        up) [ -n "${FAKE_UP_HANG:-}" ] && exec sleep 30; [ -n "${FAKE_UP_FAIL:-}" ] && exit 1; exit 0 ;;
      esac
    done ;;
  ps) echo "  kafka: Up 5 minutes (health: starting)" ;;
  inspect) exit 0 ;;
  logs) echo "kafka-log-line" ;;
esac
FAKE
cat >"$TMP/bin/ip" <<'FAKE'
#!/usr/bin/env bash
echo "1.1.1.1 via 10.0.0.1 dev eth0 src ${FAKE_VM_IP:-10.0.0.77} uid 1000"
FAKE
# Fake timeout (BSD/macOS has none): timeout [--kill-after=N] SECONDS cmd... -> exit 124 on expiry.
cat >"$TMP/bin/timeout" <<'FAKE'
#!/usr/bin/env bash
[[ "$1" == --kill-after=* ]] && shift
secs="$1"; shift
"$@" &
pid=$!
( sleep "$secs"; kill "$pid" 2>/dev/null ) >/dev/null 2>&1 &
wd=$!
wait "$pid"; rc=$?
kill "$wd" 2>/dev/null
[ "$rc" -eq 143 ] && rc=124
exit "$rc"
FAKE
chmod +x "$TMP/bin/docker" "$TMP/bin/ip" "$TMP/bin/timeout"
export FAKE_LOG="$TMP/docker.log"

pass=0 fail=0
check() { if grep -qF -- "$2" <<<"$3"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL $1: expected '$2' in:"; echo "$3" | sed 's/^/    /'; fi; }
# new_repo: a fake checkout under $TMP/vss with compose files and an env file.
new_repo() {
  rm -rf "$TMP/vss"; : >"$FAKE_LOG"
  mkdir -p "$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident"
  : >"$TMP/vss/deploy/docker/compose.yml"
  : >"$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident/compose.override.yml"
  printf 'HOST_IP=%s\nSECRET=keepme\n' "${1:-10.0.0.77}" >"$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote"
}
run() { bash "$SUT" "$TMP/vss" "" 30 "${UP_TIMEOUT:-5}" redis 2>&1; echo "rc=$?"; }
envf="$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote"

rm -rf "$TMP/vss"; out="$(run)"; check "no repo" "rc=10" "$out"; check "no repo msg" "no checkout at" "$out"
new_repo; rm "$envf"; out="$(run)"; check "no env" "rc=11" "$out"; check "no env msg" "cp " "$out"
new_repo; out="$(FAKE_DOCKER_DOWN=1 run)"; check "docker down" "rc=12" "$out"
new_repo; out="$(run)"; check "happy" "rc=0" "$out"; check "images present" "all images present" "$out"
new_repo; out="$(FAKE_MISSING_IMAGE=1 run)"; check "pull" "pulling registry images" "$out"; check "pull rc" "rc=0" "$out"
check "pull ran" "pull --ignore-buildable" "$(cat "$FAKE_LOG")"
new_repo; out="$(FAKE_MISSING_IMAGE=1 FAKE_PULL_FAIL=1 run)"; check "pull fail" "rc=13" "$out"; check "pull fail hint" "NGC login" "$out"
new_repo 10.9.9.9; out="$(run)"; check "host ip fixed" "HOST_IP is now 10.0.0.77" "$out"
check "host ip file" "HOST_IP=10.0.0.77" "$(cat "$envf")"; check "other keys kept" "SECRET=keepme" "$(cat "$envf")"
check "backup made" "HOST_IP=10.9.9.9" "$(cat "$envf".bak-*)"
new_repo; out="$(FAKE_UP_FAIL=1 run)"; check "up fail" "rc=14" "$out"
new_repo; SECONDS=0; out="$(FAKE_UP_HANG=1 UP_TIMEOUT=2 run)"
check "up timeout" "rc=124" "$out"; check "up timeout msg" "health check is stuck" "$out"; check "diagnostics" "kafka-log-line" "$out"
[ "$SECONDS" -lt 25 ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL timeout took ${SECONDS}s"; }

echo "vm-ensure-docker: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
