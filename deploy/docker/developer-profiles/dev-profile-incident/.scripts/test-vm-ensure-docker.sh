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
[ "$1" = compose ] && echo "ENV VSS_APPS_DIR=${VSS_APPS_DIR:-} VSS_DATA_DIR=${VSS_DATA_DIR:-}" >>"$FAKE_LOG"
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
  printf 'HOST_IP=%s\nSECRET=keepme\n' "${1:-10.0.0.77}" >"$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident/.env.remote"
}
run() { bash "$SUT" "$TMP/vss" "" 30 "${UP_TIMEOUT:-5}" redis 2>&1; echo "rc=$?"; }
pdir="$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident"
envf="$pdir/.env.remote"

rm -rf "$TMP/vss"; out="$(run)"; check "no repo" "rc=10" "$out"; check "no repo msg" "no checkout at" "$out"
new_repo; rm "$envf"; out="$(run)"; check "no env" "rc=11" "$out"; check "no env msg" "/.env /" "$out"; check "no env names new file" ".env.remote" "$out"
new_repo; : >"$TMP/vss/deploy/docker/developer-profiles/dev-profile-incident/compose.unused.env"; out="$(run)"; check "unused env ok" "rc=0" "$out"
check "unused env before real env" "compose.unused.env --env-file developer-profiles/dev-profile-incident/.env.remote" "$(cat "$FAKE_LOG")"
new_repo; out="$(run)"; check "no unused env still ok" "rc=0" "$out"
new_repo; out="$(FAKE_DOCKER_DOWN=1 run)"; check "docker down" "rc=12" "$out"
new_repo; out="$(run)"; check "happy" "rc=0" "$out"; check "images present" "all images present" "$out"
new_repo; out="$(FAKE_MISSING_IMAGE=1 run)"; check "pull" "pulling registry images" "$out"; check "pull rc" "rc=0" "$out"
check "pull ran" "pull --ignore-buildable" "$(cat "$FAKE_LOG")"
new_repo; out="$(FAKE_MISSING_IMAGE=1 FAKE_PULL_FAIL=1 run)"; check "pull fail" "rc=13" "$out"; check "pull fail hint" "NGC login" "$out"
new_repo 10.9.9.9; out="$(run)"; check "host ip fixed" "HOST_IP is now 10.0.0.77" "$out"
check "host ip file" "HOST_IP=10.0.0.77" "$(cat "$envf")"; check "other keys kept" "SECRET=keepme" "$(cat "$envf")"
check "backup made" "HOST_IP=10.9.9.9" "$(cat "$envf".bak-*)"
# HOST_IP blank or missing is filled from the VM's address (backup first), like a stale one.
new_repo; printf 'HOST_IP=\nSECRET=keepme\n' >"$envf"; out="$(run)"; check "blank host ip" "blank or missing" "$out"; check "blank host ip rc" "rc=0" "$out"
check "blank host ip file" "HOST_IP=10.0.0.77" "$(cat "$envf")"; check "blank host ip backup" "SECRET=keepme" "$(cat "$envf".bak-*)"
new_repo; printf 'SECRET=keepme\n' >"$envf"; out="$(run)"; check "missing host ip" "blank or missing" "$out"
check "missing host ip appended" "HOST_IP=10.0.0.77" "$(cat "$envf")"; check "missing host ip keeps keys" "SECRET=keepme" "$(cat "$envf")"
new_repo 10.0.0.77; out="$(run)"; check "right host ip untouched" "rc=0" "$out"
[ -z "$(ls "$envf".bak-* 2>/dev/null)" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL a correct HOST_IP was backed up"; }
# No VM address and a blank HOST_IP: fail clearly instead of starting with a blank address.
new_repo; printf 'HOST_IP=\n' >"$envf"; printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP/bin/ip"; out="$(run)"; check "no address rc" "rc=11" "$out"; check "no address msg" "cannot determine this VM's address" "$out"
check "no address file untouched" "HOST_IP=" "$(cat "$envf")"
printf '#!/usr/bin/env bash\necho "1.1.1.1 via 10.0.0.1 dev eth0 src ${FAKE_VM_IP:-10.0.0.77} uid 1000"\n' >"$TMP/bin/ip"
# A known HOST_IP with no VM address is left alone.
new_repo 10.9.9.9; printf '#!/usr/bin/env bash\nexit 1\n' >"$TMP/bin/ip"; out="$(run)"; check "no address, known ip" "rc=0" "$out"
printf '#!/usr/bin/env bash\necho "1.1.1.1 via 10.0.0.1 dev eth0 src ${FAKE_VM_IP:-10.0.0.77} uid 1000"\n' >"$TMP/bin/ip"

# VSS_APPS_DIR and VSS_DATA_DIR: blank or missing get the checkout defaults for the run; a filled-in value wins; the file is never changed.
new_repo; out="$(run)"; log="$(cat "$FAKE_LOG")"
check "apps dir default" "VSS_APPS_DIR=$TMP/vss/deploy/docker VSS_DATA_DIR=$TMP/vss/.data" "$log"
check "defaults leave the file" "SECRET=keepme" "$(cat "$envf")"
[ ! -e "$TMP/vss/.data" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL the script created the data directory"; }
new_repo; printf 'HOST_IP=10.0.0.77\nVSS_APPS_DIR=\nVSS_DATA_DIR=\n' >"$envf"; out="$(run)"
check "blank dirs default" "VSS_APPS_DIR=$TMP/vss/deploy/docker VSS_DATA_DIR=$TMP/vss/.data" "$(cat "$FAKE_LOG")"
new_repo; printf 'HOST_IP=10.0.0.77\nVSS_APPS_DIR=/opt/apps\nVSS_DATA_DIR=/mnt/data\n' >"$envf"; out="$(run)"
check "filled dirs win" "VSS_APPS_DIR= VSS_DATA_DIR=" "$(cat "$FAKE_LOG")"

# Both env file names: .env.remote wins and the script says so; the old name alone still works.
new_repo; printf 'HOST_IP=10.0.0.77\nSECRET=old\n' >"$pdir/generated.env.remote"; out="$(run)"
check "both names rc" "rc=0" "$out"; check "both names say so" "both .env.remote and generated.env.remote exist; using .env.remote" "$out"
check "both names use new" "developer-profiles/dev-profile-incident/.env.remote" "$(cat "$FAKE_LOG")"
new_repo; mv "$envf" "$pdir/generated.env.remote"; out="$(run)"; check "old name only rc" "rc=0" "$out"
check "old name used" "developer-profiles/dev-profile-incident/generated.env.remote" "$(cat "$FAKE_LOG")"
new_repo 10.9.9.9; mv "$envf" "$pdir/generated.env.remote"; out="$(run)"
check "old name host ip fixed" "HOST_IP=10.0.0.77" "$(cat "$pdir/generated.env.remote")"
new_repo; out="$(FAKE_UP_FAIL=1 run)"; check "up fail" "rc=14" "$out"
new_repo; SECONDS=0; out="$(FAKE_UP_HANG=1 UP_TIMEOUT=2 run)"
check "up timeout" "rc=124" "$out"; check "up timeout msg" "health check is stuck" "$out"; check "diagnostics" "kafka-log-line" "$out"
[ "$SECONDS" -lt 25 ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo "FAIL timeout took ${SECONDS}s"; }

echo "vm-ensure-docker: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
