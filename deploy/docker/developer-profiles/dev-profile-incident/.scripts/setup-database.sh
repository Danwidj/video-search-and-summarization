#!/usr/bin/env bash
#
# setup-database.sh — LAPTOP SIDE ONLY. Builds the whole schema (every table and function) on an EMPTY
# Supabase project by applying supabase/migrations/ in file-name order, then runs supabase/tests/security_check.sql.
#
#   ./.scripts/setup-database.sh --env-file .env.local
#
# The target is explicit: --env-file names a file, and only its INCIDENT_DB_DSN line is read (the file is never
# sourced; the value is never printed, and an error from the database has it replaced by <dsn>). With no
# --env-file, or no INCIDENT_DB_DSN in it, the script stops and touches nothing. The target must be a database
# you may fill: if public already has any table, or the migration history is not empty, the script stops
# without applying anything.
#
# Why not `supabase db push`: two migrations share the version 20261028090000 (r2_rename and
# search_evidence_items_video_id; applied migrations cannot be renamed), so the CLI cannot apply the folder to
# an empty database ("duplicate key ... schema_migrations_pkey"). This script applies the files itself and
# records each version in supabase_migrations.schema_migrations as the CLI does, keeping the first of a shared
# version, exactly as the live finals history does, so a later `supabase db push` works on the new database.
#
# Each file runs as it is (some hold their own BEGIN/COMMIT), so a failure part-way leaves a part-built
# database: drop and recreate it before running again. Needs `uv`; the database needs the API roles anon,
# authenticated and service_role (every Supabase project has them).

set -euo pipefail

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATIONS_DIR="${PROFILE_DIR}/supabase/migrations"
SECURITY_CHECK="${PROFILE_DIR}/supabase/tests/security_check.sql"

env_file=""
while [ $# -gt 0 ]; do
  case "$1" in
    --env-file)
      [ $# -ge 2 ] || { echo "setup-database.sh: --env-file needs a file" >&2; exit 2; }
      env_file="$2"
      shift 2
      ;;
    -h | --help)
      sed -n '3,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "setup-database.sh: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [ -z "$env_file" ]; then
  echo "setup-database.sh: no target. Pass --env-file <file> holding INCIDENT_DB_DSN, the connection string of an empty database." >&2
  exit 2
fi
if [ ! -f "$env_file" ]; then
  echo "setup-database.sh: ${env_file} is not a file." >&2
  exit 2
fi

dsn="$(sed -nE 's/^[[:space:]]*(export[[:space:]]+)?INCIDENT_DB_DSN=[[:space:]]*//p' "$env_file" \
  | tail -n 1 | sed -E "s/[[:space:]]+#.*$//; s/^[\"']//; s/[\"'][[:space:]]*$//")"
if [ -z "$dsn" ]; then
  echo "setup-database.sh: ${env_file} has no INCIDENT_DB_DSN value." >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "setup-database.sh: uv is not installed (https://docs.astral.sh/uv/)." >&2
  exit 2
fi

SETUP_DB_DSN="$dsn" uv run --no-project --python 3.12 --with 'psycopg[binary]' python - "$MIGRATIONS_DIR" "$SECURITY_CHECK" <<'PY'
import os
import pathlib
import sys

import psycopg

dsn = os.environ["SETUP_DB_DSN"]
migrations_dir, security_check = (pathlib.Path(arg) for arg in sys.argv[1:3])


def fail(message: str) -> None:
    print(f"setup-database.sh: {message.replace(dsn, '<dsn>')}", file=sys.stderr)
    sys.exit(1)


def first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0]


files = sorted(migrations_dir.glob("*.sql"))
if not files:
    fail(f"no migrations in {migrations_dir}")

try:
    conn = psycopg.connect(dsn, autocommit=True)
except psycopg.Error as exc:
    fail(f"cannot connect to the target: {first_line(exc)}")

tables = conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'").fetchone()[0]
recorded = 0
if conn.execute("SELECT to_regclass('supabase_migrations.schema_migrations') IS NOT NULL").fetchone()[0]:
    recorded = conn.execute("SELECT count(*) FROM supabase_migrations.schema_migrations").fetchone()[0]
if tables or recorded:
    fail(f"the target already has the schema ({tables} tables in public, {recorded} recorded migrations). Nothing was applied.")

conn.execute("CREATE SCHEMA IF NOT EXISTS supabase_migrations")
conn.execute("CREATE TABLE IF NOT EXISTS supabase_migrations.schema_migrations (version text NOT NULL PRIMARY KEY, statements text[], name text)")
for path in files:
    version, _, name = path.stem.partition("_")
    try:
        conn.execute(path.read_text())
    except psycopg.Error as exc:
        fail(f"{path.name} failed: {first_line(exc)}\nThe target is part-built: drop and recreate it before running again.")
    conn.execute(
        "INSERT INTO supabase_migrations.schema_migrations (version, statements, name) VALUES (%s, '{}', %s) ON CONFLICT (version) DO NOTHING",
        (version, name),
    )
    print(f"applied {path.name}")

problems = conn.execute(security_check.read_text()).fetchall()
if problems:
    fail(f"security_check.sql returned {len(problems)} row(s): {problems}")
print(f"setup-database.sh: {len(files)} migrations applied; security_check.sql returned 0 rows.")
PY
