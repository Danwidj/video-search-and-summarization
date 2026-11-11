<!--
agents:
  read-when: Writing, testing or applying a finals migration, or running the SQL harness or the security check.
  owns: the supabase/ layout, the harness commands, the finals push steps and the migration checklist.
  rules: Never edit, rename or merge an applied migration. Never push to or edit archived/supabase/midterm/. Applying to the live finals database needs the owner's approval.
  check: cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py
-->

# Supabase

The schema of the incident profile. Finals is the live database for every service and is built from [migrations](migrations/): one baseline, then one file per later change. To build a new database from empty, run [`.scripts/setup-database.sh`](../.scripts/setup-database.sh). Midterm (`rfevukimyftzbxlehwel`) is a frozen, read-only record in [archived/supabase/midterm](../archived/supabase/midterm/README.md): never push to it.

This folder is the `--workdir` target of the `supabase` CLI. It is not an initialised CLI project: there is no `config.toml`, and `supabase db push --workdir <dir> --db-url <url>` works against the bare `migrations/` folder.

## Layout

| Path | What it holds |
|---|---|
| [migrations/](migrations/) | The finals schema: `20261020000000_finals_baseline.sql` builds it from empty, and later files change it |
| [tests/](tests/) | The SQL harness (`test_baseline.py`, `test_freeze.py`, which reads the archived midterm files), `security_check.sql`, `supabase_stub.sql`, `parity_check.py`, `rehearse.py`, `probe_api.sh` |
| [../archived/supabase/r2/](../archived/supabase/r2/) | Archived: `migrate_r2_names.py`, `backfill_content_hash.py` and their tests (one-off R2 and hash backfills) |
| [../archived/supabase/copy/](../archived/supabase/copy/) | Archived: `copy_midterm_to_finals.py` and `transform.sql`, the one-way midterm to finals copy. It targets the pre-revision schema, so do not run it |
| [../archived/supabase/midterm/](../archived/supabase/midterm/README.md) | Archived: the frozen midterm record, 14 migrations, `midterm_base_tables.sql`, freeze and unfreeze SQL |

## Test the schema

The harness needs no Supabase and no network. It runs on a throwaway local Postgres 16 with pgvector (`pgserver`), and `supabase_stub.sql` adds the API roles and Supabase's default grants, so the lockdown is tested against what a new project starts with.

```bash
cd supabase/tests
# Applies every file in ../migrations/ in order, then runs the security and behaviour tests
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py
# Midterm freeze and unfreeze on a local replica
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_freeze.py
```

## Build a new database

On an empty Supabase project, put its direct or session-pooler connection string in a file as `INCIDENT_DB_DSN` (for example `.env.local`) and run, from the profile folder:

```bash
./.scripts/setup-database.sh --env-file .env.local
```

It applies every file in `migrations/` in order, records the versions, runs `security_check.sql` and stops without applying anything if the target already has tables or recorded migrations. It does not use `supabase db push`, because two migrations share the version `20261028090000`, which the CLI cannot record on an empty database. Test it with `bash .scripts/test-setup-database.sh`.

## Building finals

`FINALS_DSN` is the finals session-pooler URL (port 5432, plain `postgresql://`, no SQLAlchemy suffix). Run from the repo root:

```bash
W=deploy/docker/developer-profiles/dev-profile-incident
supabase db push --workdir $W --db-url "$FINALS_DSN" --dry-run
supabase db push --workdir $W --db-url "$FINALS_DSN"
psql "$FINALS_DSN" -f $W/supabase/tests/security_check.sql   # expect 0 rows
FINALS_URL=... FINALS_PUBLIC_KEY=... FINALS_SERVICE_KEY=... $W/supabase/tests/probe_api.sh
# expect 401 or 403 for every public-key line, 200 for the service key
```

Finals uses the new key types: the server key is `sb_secret_...` and the public key `sb_publishable_...`, not JWTs. Send them in the `apikey` header only, as `probe_api.sh` does. The [Manage-database skill](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_) holds the connection test and the table of every key sender.

## Add a finals migration

Add `migrations/YYYYMMDDHHMMSS_<what>.sql` after the baseline. Never edit an applied migration and never add files to `archived/supabase/midterm/`. In the same PR:
- extend `tests/test_baseline.py`, which applies every file in `migrations/` in order;
- give every new table RLS and every new function `SET search_path = ''`, or the harness and `security_check.sql` fail;
- update the [Data layer](../.docs/data.md).

The file must apply cleanly to a fresh database and to the live one: use `IF NOT EXISTS`, `CREATE OR REPLACE`, guarded `DO` blocks and conditional drops. After applying, run `security_check.sql` against finals. To record an out-of-band change without running SQL, use `supabase migration repair --workdir $W --db-url "$FINALS_DSN" --status applied <YYYYMMDDHHMMSS>`.

## Read more

- [Data layer: Supabase schema](../.docs/data.md#1-supabase-postgresql-schema): tables, functions, security and R2 keys
- [Status: Database status](../.docs/status.md#3-database-status): which migrations are applied to finals
- [Architecture: Two Supabase projects](../.docs/architecture.md#two-supabase-projects-one-per-phase): which service points at which project
- [Decision log: One Supabase project per phase](../.docs/decisions.md#2026-10-20-one-supabase-project-per-phase-finals-built-from-one-baseline-midterm-frozen): why there are two projects
