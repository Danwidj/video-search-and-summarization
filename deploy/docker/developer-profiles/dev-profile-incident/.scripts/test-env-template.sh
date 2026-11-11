#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermetic checks on the committed env template (.env) and compose.unused.env:
# it sources cleanly, defines every setting once, defines a setting before any setting that
# refers to it, keeps the lines the sed-based loaders read literal, and holds no real value. It also
# checks that a VM file copied from the template, loaded the way native-services.sh loads it, defines
# every setting the agent config refers to (an unset one makes nat reject the whole config).
#
# Usage:
#   bash deploy/docker/developer-profiles/dev-profile-incident/.scripts/test-env-template.sh

set -uo pipefail

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROFILE_DIR}/.env"
UNUSED_FILE="${PROFILE_DIR}/compose.unused.env"

pass=0 fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL $*"; }

out="$(env -i bash -c 'set -eu; set -a; source "$1"' _ "$ENV_FILE" 2>&1)" && ok || bad "sourcing .env in a clean shell: ${out}"

names="$(sed -nE 's/^([A-Z][A-Z0-9_]*)=.*/\1/p' "$ENV_FILE")"
dups="$(sort <<<"$names" | uniq -d)"
[ -z "$dups" ] && ok || bad "defined twice: ${dups}"

# A ${NAME} reference must point at a setting defined on an earlier line.
defined=" "
while IFS= read -r line; do
  [[ "$line" =~ ^[A-Z][A-Z0-9_]*= ]] || continue
  name="${line%%=*}"
  rest="${line#*=}"
  while [[ "$rest" =~ \$\{([A-Za-z_][A-Za-z0-9_]*)\} ]]; do
    ref="${BASH_REMATCH[1]}"
    [[ "$defined" == *" ${ref} "* ]] && ok || bad "${name} refers to ${ref}, which is not defined above it"
    rest="${rest#*"${BASH_REMATCH[0]}"}"
  done
  defined="${defined}${name} "
done <"$ENV_FILE"

# The sed pickers in vm-host.sh, tracking-stack.sh and vm-ensure-docker.sh read these keys as plain lines.
for key in VSS_SSH_HOST HOST_IP VSS_DATA_DIR NGC_CLI_API_KEY COMPOSE_PROJECT_NAME; do
  grep -qE "^${key}=[^\$]*\$" "$ENV_FILE" && ok || bad "${key} must be a literal line (no \${} reference)"
done

# Section 1 is only what a machine must fill in. These are blank defaults the scripts supply, or optional,
# so they sit in section 2 (a filled-in value still wins), and settings nothing reads are gone.
section2="$(awk '/^# 2\. /{f=1} f' "$ENV_FILE")"
for key in HOST_IP VSS_APPS_DIR VSS_DATA_DIR VLM_MODEL VLM_GATEWAY_BASE_URL VLM_GATEWAY_API_KEY; do
  grep -qE "^${key}=$" <<<"$section2" && ok || bad "${key} must be a blank line in section 2"
done
for key in HF_TOKEN VLM_GATEWAY_URL; do
  grep -qE "^${key}=" "$ENV_FILE" && bad "${key} is read by nothing this profile starts; it must stay out of the template" || ok
done
section1="$(awk '/^# 2\. /{exit} {print}' "$ENV_FILE")"
for key in INCIDENT_SUPABASE_URL INCIDENT_SUPABASE_SERVICE_ROLE_KEY INCIDENT_DB_DSN R2_ACCOUNT_ID R2_ACCESS_KEY R2_SECRET_KEY R2_BUCKET VSS_SSH_HOST NGC_CLI_API_KEY OPENAI_API_KEY LLM_BASE_URL LLM_NAME VLM_NAME; do
  grep -qE "^${key}=$" <<<"$section1" && ok || bad "${key} must be a blank line in section 1"
done
# The header names the VM file .env.remote, not the old name.
grep -q 'cp .env .env.remote' "$ENV_FILE" && ok || bad "the .env header must say cp .env .env.remote"
grep -q 'generated.env' "$ENV_FILE" && bad "the .env header still names generated.env.remote" || ok
# git ignores the VM file here, so a real one is never committed.
( cd "$PROFILE_DIR" && git check-ignore -q .env.remote ) && ok || bad ".env.remote is not git-ignored in the profile"

# No `KEY=   # note` lines: loaders disagree on whether that is empty.
if grep -nE '^[A-Z][A-Z0-9_]*=[[:space:]]+#' "$ENV_FILE" >/dev/null; then bad "a setting has a trailing comment"; else ok; fi

# Committed file: no secret-looking value.
if grep -nE '^(NGC_CLI_API_KEY|OPENAI_API_KEY|R2_SECRET_KEY|R2_ACCESS_KEY|INCIDENT_SUPABASE_SERVICE_ROLE_KEY|INCIDENT_DB_DSN|VLM_GATEWAY_API_KEY)=.+' "$ENV_FILE" >/dev/null; then
  bad "a secret setting has a value in the committed template"
else ok; fi

# compose.unused.env only blanks names the template does not define.
overlap="$(comm -12 <(sort <<<"$names") <(sed -nE 's/^([A-Z][A-Z0-9_]*)=.*/\1/p' "$UNUSED_FILE" | sort))"
[ -z "$overlap" ] && ok || bad "in both .env and compose.unused.env: ${overlap}"
if grep -vE '^(#|$|[A-Z][A-Z0-9_]*=$)' "$UNUSED_FILE" >/dev/null; then bad "compose.unused.env holds a value"; else ok; fi

# The agent config must find every ${NAME} it refers to set to a value in a file built from the template,
# loaded by vm_env_load with a stand-in `ip` (that is where HOST_IP comes from on the VM). nat treats an
# unset or blank ${NAME} as no string and rejects the config. The section 1 settings get a dummy value, as
# a machine fills them in; the optional Weave alias may stay blank. Comment lines and ${NAME:-default} references are skipped; the fallback
# inside a default still counts.
AGENT_CONFIG="${PROFILE_DIR}/../dev-profile-base/vss-agent/configs/config.yml"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
printf '#!/usr/bin/env bash\necho "1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.77 uid 0"\n' >"$TMP/bin/ip"
chmod +x "$TMP/bin/ip"
sed -E '/^# 2\. /,$!s/^([A-Z][A-Z0-9_]*)=$/\1=dummy/' "$ENV_FILE" >"$TMP/.env.remote"
needed="$(grep -vE '^[[:space:]]*#' "$AGENT_CONFIG" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*\}' | tr -d '${}' | sort -u)"
[ -n "$needed" ] && ok || bad "found no \${NAME} references in ${AGENT_CONFIG}"
unset_names="$(env -i PATH="$TMP/bin:$PATH" bash -c '
  source "$1/.scripts/env-file.sh"
  vm_env_load "$2" "$1" || exit 1
  for n in $3; do
    case " $4 " in *" $n "*) continue ;; esac
    [ -n "${!n:-}" ] || echo "$n"
  done' _ "$PROFILE_DIR" "$TMP/.env.remote" "$needed" "WEAVE_WORKFLOW_ALIAS" 2>&1)"
[ -z "$unset_names" ] && ok || bad "the agent config refers to settings a template-built file leaves unset or blank: $(tr '\n' ' ' <<<"$unset_names")"

echo "env-template: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
