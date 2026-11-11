#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Hermetic checks on setup-database.sh against a throwaway local Postgres (the pgserver binaries the SQL
# harness uses; no Supabase, no network): it refuses without an explicit target, builds the whole schema on an
# empty database, never prints the connection string, and refuses a second run without changing anything.
# Needs uv.
#
# Usage:
#   bash deploy/docker/developer-profiles/dev-profile-incident/.scripts/test-setup-database.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
SETUP="${SCRIPT_DIR}/setup-database.sh"
PY=(uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python)

if ! command -v uv >/dev/null 2>&1; then
  echo "setup-database: SKIP (uv is not installed)"
  exit 0
fi

TMP="$(mktemp -d)"
server_pid=""
cleanup() {
  [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null
  [ -n "$server_pid" ] && wait "$server_pid" 2>/dev/null
  rm -rf "$TMP"
}
trap cleanup EXIT

pass=0 fail=0
ok() { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); echo "FAIL $*"; }

# Without a target, nothing runs.
out="$("$SETUP" 2>&1)" && bad "ran without --env-file" || { [[ "$out" == *"no target"* ]] && ok || bad "no-target message: ${out}"; }
out="$("$SETUP" --env-file "${TMP}/missing.env" 2>&1)" && bad "ran with a missing env file" || ok
printf 'OTHER=1\n' >"${TMP}/empty.env"
out="$("$SETUP" --env-file "${TMP}/empty.env" 2>&1)" && bad "ran with no INCIDENT_DB_DSN" || { [[ "$out" == *"no INCIDENT_DB_DSN"* ]] && ok || bad "no-DSN message: ${out}"; }

# A throwaway Postgres on 127.0.0.1 with the Supabase API roles, started in the background; it prints its port.
cat >"${TMP}/server.py" <<'PY'
import atexit, pathlib, socket, sys, tempfile, time
import psycopg
from pgserver._commands import initdb, pg_ctl

stub = pathlib.Path(sys.argv[1]).read_text()
root = pathlib.Path(tempfile.mkdtemp(prefix="setup-db-"))
data = root / "pgdata"
with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
initdb(["-U", "postgres", "-A", "trust", "-E", "UTF8"], pgdata=data)
pg_ctl(["-w", "-o", f"-h 127.0.0.1 -p {port} -k {root}", "-l", str(root / "log"), "start"], pgdata=data)
atexit.register(lambda: pg_ctl(["-m", "immediate", "stop"], pgdata=data))
with psycopg.connect(f"postgresql://postgres@127.0.0.1:{port}/postgres", autocommit=True) as conn:
    conn.execute(stub)
print(port, flush=True)
time.sleep(600)
PY
"${PY[@]}" "${TMP}/server.py" "${PROFILE_DIR}/supabase/tests/supabase_stub.sql" >"${TMP}/port" 2>"${TMP}/server.err" &
server_pid=$!
for _ in $(seq 1 120); do [ -s "${TMP}/port" ] && break; sleep 1; done
port="$(cat "${TMP}/port")"
if [ -z "$port" ]; then
  bad "the throwaway Postgres did not start: $(tail -n 3 "${TMP}/server.err")"
  echo "setup-database: ${pass} passed, ${fail} failed"
  exit 1
fi

secret="pw-not-for-output"
printf 'OPENAI_API_KEY=other-secret\nINCIDENT_DB_DSN="postgresql://postgres:%s@127.0.0.1:%s/postgres?sslmode=disable"\n' "$secret" "$port" >"${TMP}/target.env"
count() { "${PY[@]}" - "$port" "$1" <<'PY' 2>/dev/null
import sys, psycopg
with psycopg.connect(f"postgresql://postgres@127.0.0.1:{sys.argv[1]}/postgres") as conn:
    print(conn.execute(sys.argv[2]).fetchone()[0])
PY
}

files="$(find "${PROFILE_DIR}/supabase/migrations" -name '*.sql' | wc -l | tr -d ' ')"
versions="$(find "${PROFILE_DIR}/supabase/migrations" -name '*.sql' -exec basename {} \; | cut -d_ -f1 | sort -u | wc -l | tr -d ' ')"

first="$("$SETUP" --env-file "${TMP}/target.env" 2>&1)" && ok || bad "first run failed: ${first}"
[[ "$first" == *"${files} migrations applied; security_check.sql returned 0 rows"* ]] && ok || bad "first run summary: ${first}"
[ "$(count "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('videos','report_revisions','evidence_crops','analysis_jobs')")" = 4 ] && ok || bad "core tables missing after the first run"
[ "$(count "SELECT count(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace AND proname = 'search_evidence_items'")" -ge 1 ] && ok || bad "search_evidence_items missing after the first run"
[ "$(count "SELECT count(*) FROM supabase_migrations.schema_migrations")" = "$versions" ] && ok || bad "history does not hold one row per version (${versions})"

tables_before="$(count "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")"
second="$("$SETUP" --env-file "${TMP}/target.env" 2>&1)" && bad "second run succeeded" || { [[ "$second" == *"already has the schema"* ]] && ok || bad "second run message: ${second}"; }
[ "$(count "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")" = "$tables_before" ] && ok || bad "second run changed the tables"

for text in "$first" "$second"; do
  [[ "$text" == *"$secret"* || "$text" == *"other-secret"* ]] && bad "output holds a value from the env file" || ok
done

echo "setup-database: ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
