#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermetic checks on the committed env template (.env) and compose.unused.env:
# it sources cleanly, defines every setting once, defines a setting before any setting that
# refers to it, keeps the lines the sed-based loaders read literal, and holds no real value.
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

# No `KEY=   # note` lines: loaders disagree on whether that is empty.
if grep -nE '^[A-Z][A-Z0-9_]*=[[:space:]]+#' "$ENV_FILE" >/dev/null; then bad "a setting has a trailing comment"; else ok; fi

# Committed file: no secret-looking value.
if grep -nE '^(NGC_CLI_API_KEY|HF_TOKEN|OPENAI_API_KEY|R2_SECRET_KEY|R2_ACCESS_KEY|INCIDENT_SUPABASE_SERVICE_ROLE_KEY|INCIDENT_DB_DSN|VLM_GATEWAY_API_KEY)=.+' "$ENV_FILE" >/dev/null; then
  bad "a secret setting has a value in the committed template"
else ok; fi

# compose.unused.env only blanks names the template does not define.
overlap="$(comm -12 <(sort <<<"$names") <(sed -nE 's/^([A-Z][A-Z0-9_]*)=.*/\1/p' "$UNUSED_FILE" | sort))"
[ -z "$overlap" ] && ok || bad "in both .env and compose.unused.env: ${overlap}"
if grep -vE '^(#|$|[A-Z][A-Z0-9_]*=$)' "$UNUSED_FILE" >/dev/null; then bad "compose.unused.env holds a value"; else ok; fi

echo "env-template: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
