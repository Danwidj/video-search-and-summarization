#!/usr/bin/env bash
#
# Hermetic test for vm-stop-backend.sh (the VM-side stop step start.sh pipes over SSH).
# Fake `docker`, `flock` and `timeout` stand in for the VM.
#   bash .scripts/test-vm-stop-backend.sh

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUT="$SCRIPT_DIR/vm-stop-backend.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
export PATH="$TMP/bin:$PATH"

# Fake flock: Python wrapper around fcntl.flock implementing -s, -x, -n, -w <sec>
cat >"$TMP/bin/flock" <<'EOF'
#!/usr/bin/env python3
import sys, os, fcntl, time

args = sys.argv[1:]
shared = False
exclusive = True
nonblock = False
timeout = 0
i = 0
while i < len(args):
    a = args[i]
    if a in ('-s', '--shared'):
        shared = True
        exclusive = False
    elif a in ('-x', '--exclusive'):
        exclusive = True
        shared = False
    elif a in ('-n', '--nb', '--nonblock'):
        nonblock = True
    elif a in ('-w', '--wait', '--timeout'):
        i += 1
        timeout = float(args[i])
    elif not a.startswith('-'):
        break
    i += 1

if i >= len(args):
    sys.exit(1)

target = args[i]
cmd = args[i+1:]

if target.isdigit():
    fd = int(target)
    should_close = False
else:
    fd = os.open(target, os.O_RDONLY | os.O_CREAT, 0o666)
    should_close = True

flags = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
if nonblock or timeout > 0:
    flags |= fcntl.LOCK_NB

start_time = time.time()
while True:
    try:
        fcntl.flock(fd, flags)
        break
    except (BlockingIOError, IOError):
        if timeout > 0 and (time.time() - start_time) < timeout:
            time.sleep(0.05)
            continue
        sys.exit(1)

if cmd:
    pid = os.fork()
    if pid == 0:
        os.execvp(cmd[0], cmd)
    _, status = os.waitpid(pid, 0)
    sys.exit(os.waitstatus_to_exitcode(status))
else:
    sys.exit(0)
EOF
chmod +x "$TMP/bin/flock"

# Fake docker: logs calls to $TMP/docker.log
export FAKE_DOCKER_LOG="$TMP/docker.log"
cat >"$TMP/bin/docker" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >>"$FAKE_DOCKER_LOG"
case "$1" in
  info)
    [ -z "${FAKE_DOCKER_DOWN:-}" ] ;;
  compose)
    for a in "$@"; do
      case "$a" in
        ps)
          echo "c_streamprocessing c_redis"
          exit 0
          ;;
      esac
    done
    ;;
  ps)
    echo "mdx-redis-1"
    echo "vss-haproxy-ingress"
    exit 0
    ;;
  stop)
    [ -n "${FAKE_STOP_FAIL:-}" ] && exit 1
    exit 0
    ;;
esac
FAKE
chmod +x "$TMP/bin/docker"

# Fake timeout (Python-based so no leaked sleep processes)
cat >"$TMP/bin/timeout" <<'FAKE'
#!/usr/bin/env bash
[[ "$1" == --kill-after=* ]] && shift
secs="$1"; shift
python3 -c "
import sys, subprocess
secs = float(sys.argv[1])
cmd = sys.argv[2:]
try:
    p = subprocess.run(cmd, timeout=secs)
    sys.exit(p.returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)
" "$secs" "$@"
FAKE
chmod +x "$TMP/bin/timeout"

# Setup fake repo root with fake native-services.sh
FAKE_REPO="$TMP/repo"
export FAKE_NATIVE_LOG="$TMP/native.log"
mkdir -p "$FAKE_REPO/deploy/docker/developer-profiles/dev-profile-incident/.scripts"
mkdir -p "$FAKE_REPO/deploy/docker"
: >"$FAKE_REPO/deploy/docker/compose.yml"
cat >"$FAKE_REPO/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh" <<'FAKE'
#!/usr/bin/env bash
echo "$*" >>"${FAKE_NATIVE_LOG:-/dev/null}"
if [ "${FAKE_NATIVE_FAIL:-}" = "1" ]; then
  exit 1
fi
exit 0
FAKE
chmod +x "$FAKE_REPO/deploy/docker/developer-profiles/dev-profile-incident/.scripts/native-services.sh"

pass=0 fail=0
# shellcheck disable=SC2001
check() {
  if grep -qF -- "$2" <<<"$3"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    echo "FAIL $1: expected '$2' in:"
    echo "$3" | sed 's/^/    /'
  fi
}

DOCKER_SVCS="vss-vios-streamprocessing redis vss-haproxy-ingress"
NATIVE_SVCS="vss-agent"

# Test 1: Another session holds shared lock -> do not stop backend
LOCK_FILE="$TMP/active-runs.lock"
: >"$LOCK_FILE"
: >"$FAKE_DOCKER_LOG"; : >"$FAKE_NATIVE_LOG"
HOLDER_PIPE="$TMP/holder.pipe"
mkfifo "$HOLDER_PIPE"
python3 -c "
import fcntl, time, os
fd = open('$LOCK_FILE', 'r')
fcntl.flock(fd, fcntl.LOCK_SH)
with open('$HOLDER_PIPE', 'w') as p:
    p.write('READY\n')
time.sleep(5)
" &
HOLDER_PID=$!
read -r _ <"$HOLDER_PIPE"
rm -f "$HOLDER_PIPE"

out="$(bash "$SUT" "$LOCK_FILE" "$FAKE_REPO" "$DOCKER_SVCS" "$NATIVE_SVCS" 2>&1)"; rc=$?
check "shared lock held rc" "0" "$rc"
check "shared lock message" "other active sessions remain on the VM; leaving backend running." "$out"
check "no docker stop when shared lock held" "" "$(cat "$FAKE_DOCKER_LOG")"
check "no native stop when shared lock held" "" "$(cat "$FAKE_NATIVE_LOG")"

kill "$HOLDER_PID" 2>/dev/null || true
wait "$HOLDER_PID" 2>/dev/null || true
sleep 0.2

# Test 2: Last session exits -> stops native and Docker services
: >"$FAKE_DOCKER_LOG"; : >"$FAKE_NATIVE_LOG"
out="$(bash "$SUT" "$LOCK_FILE" "$FAKE_REPO" "$DOCKER_SVCS" "$NATIVE_SVCS" 2>&1)"; rc=$?
check "last exit rc" "0" "$rc"
check "last exit message" "last active session exited; stopping backend services on the VM..." "$out"
check "native stop called" "stop vss-agent" "$(cat "$FAKE_NATIVE_LOG")"
check "docker stop called" "stop c_streamprocessing c_redis" "$(cat "$FAKE_DOCKER_LOG")"
check "success message" "backend services stopped successfully." "$out"

# Test 3: Containers are never removed (rm, down, -v never invoked)
if grep -Eq "(rm|down|-v)" "$FAKE_DOCKER_LOG"; then
  fail=$((fail + 1))
  echo "FAIL: destructive docker command found in $FAKE_DOCKER_LOG"
else
  pass=$((pass + 1))
fi

# Test 4: Lock file creation when missing
rm -f "$LOCK_FILE"
: >"$FAKE_DOCKER_LOG"; : >"$FAKE_NATIVE_LOG"
out="$(bash "$SUT" "$LOCK_FILE" "$FAKE_REPO" "$DOCKER_SVCS" "$NATIVE_SVCS" 2>&1)"; rc=$?
check "missing lock file rc" "0" "$rc"
check "lock file recreated" "true" "$([ -f "$LOCK_FILE" ] && echo true || echo false)"

# Test 5: Non-fatal error handling when stop commands fail
: >"$FAKE_DOCKER_LOG"; : >"$FAKE_NATIVE_LOG"
out="$(FAKE_STOP_FAIL=1 FAKE_NATIVE_FAIL=1 bash "$SUT" "$LOCK_FILE" "$FAKE_REPO" "$DOCKER_SVCS" "$NATIVE_SVCS" 2>&1)"; rc=$?
check "failure is non-fatal rc" "0" "$rc"
check "docker stop warning" "warning: docker stop exited with" "$out"
check "native stop warning" "warning: native-services.sh stop exited with" "$out"

# Test 6: start.sh cleanup behaviour and opt-out
START_SH="$SCRIPT_DIR/../start.sh"
# Test unknown argument usage output
out="$(bash "$START_SH" --unknown-flag 2>&1 || true)"
check "usage mentions keep-backend" "--keep-backend" "$out"

# Test cleanup opt-out via VSS_STOP_ON_LAST_EXIT=false
out="$(bash -c "
  VSS_START_MODE=vm
  VSS_STOP_ON_LAST_EXIT=false
  LOCK_HELD=1
  LOCK_SSH_PID=''
  TUNNEL_LOG=''
  TUNNEL_PID=''
  VLM_GATEWAY_PID=''
  MOCK_BACKEND_PID=''
  $(sed -n '/^cleanup() {/,/^}/p' "$START_SH")
  cleanup
" 2>&1)"
check "opt-out message" "VSS_STOP_ON_LAST_EXIT is disabled; leaving backend running" "$out"

# Test cleanup when stop fails over SSH (must be non-fatal)
cat >"$TMP/bin/ssh" <<'FAKE'
#!/usr/bin/env bash
echo "ssh: connection dropped" >&2
exit 255
FAKE
chmod +x "$TMP/bin/ssh"

out="$(bash -c "
  export PATH='$TMP/bin:\$PATH'
  VSS_START_MODE=vm
  VSS_STOP_ON_LAST_EXIT=true
  LOCK_HELD=1
  LOCK_SSH_PID=''
  TUNNEL_LOG=''
  TUNNEL_PID=''
  VLM_GATEWAY_PID=''
  MOCK_BACKEND_PID=''
  VSS_SSH_TARGET='test@vm'
  VSS_SSH_OPTS=()
  VSS_LOCK_FILE='/tmp/test.lock'
  VSS_REPO_ROOT='/srv/vss'
  SCRIPT_DIR='$SCRIPT_DIR'
  $(sed -n '/^cleanup() {/,/^}/p' "$START_SH")
  cleanup
" 2>&1)"; rc=$?
check "ssh failure in cleanup is non-fatal rc" "0" "$rc"
check "ssh failure warning" "warning: failed to check or stop VM backend services" "$out"

echo "vm-stop-backend: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
