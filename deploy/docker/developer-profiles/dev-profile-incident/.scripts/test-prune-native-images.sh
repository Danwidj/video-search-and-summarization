#!/usr/bin/env bash
#
# Hermetic executable-interface test for the incident-operate-vm pruning
# helper. Fake Docker is placed first on PATH, so no daemon or cache is used.

set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
export PATH="$TMP/bin:$PATH"

cat >"$TMP/bin/docker" <<'FAKE'
#!/usr/bin/env bash
printf 'docker %s\n' "$*" >> "${FAKE_DOCKER_LOG}"
case "$1 ${2:-}" in
  "system df") echo "TYPE TOTAL ACTIVE SIZE RECLAIMABLE" ;;
  "ps -a") exit 0 ;;
  "images") exit 0 ;;
  "image prune") exit 0 ;;
  *) exit 0 ;;
esac
FAKE
chmod +x "$TMP/bin/docker"
export FAKE_DOCKER_LOG="$TMP/docker.log"

output="$($SCRIPT_DIR/../skills/incident-operate-vm/scripts/prune-native-images.sh --non-interactive 2>&1)"
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "$output"
  echo "FAIL non-interactive prune exited $rc"
  exit 1
fi
if grep -qF "Proceed with pruning" <<<"$output"; then
  echo "$output"
  echo "FAIL non-interactive prune prompted"
  exit 1
fi
if ! grep -qF -- "--non-interactive was supplied" <<<"$output"; then
  echo "$output"
  echo "FAIL non-interactive mode was not reported"
  exit 1
fi
if ! grep -qF "docker image prune -f --filter until=24h" "$FAKE_DOCKER_LOG"; then
  cat "$FAKE_DOCKER_LOG"
  echo "FAIL prune interface did not reach Docker"
  exit 1
fi

echo "prune-native-images: non-interactive interface passed"
