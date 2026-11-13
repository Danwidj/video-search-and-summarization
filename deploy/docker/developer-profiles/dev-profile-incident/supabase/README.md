<!--
agents:
  read-when: Writing, testing or applying a finals migration, or running the SQL harness or the security check.
  owns: the supabase/ layout, the harness commands, the finals push steps and the migration checklist.
  rules: Never edit, rename or merge an applied migration. Never push to or edit archived/supabase/midterm/. Applying to the live finals database needs the owner's approval.
  check: cd supabase/tests && uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py
-->

# Supabase

The schema of the incident profile. Finals is the live database for every service and is built from [migrations](migrations/): one baseline, then one file per later change. To build a new database from empty, run [`.scripts/setup-database.sh`](../.scripts/setup-database.sh). Midterm (`rfevukimyftzbxlehwel`) is a frozen, read-only record in [archived/supabase/midterm](../archived/supabase/midterm/README.md): never push to it.

The profile folder is the `--workdir` target of the `supabase` CLI, and the CLI reads `migrations/` from it. It is not an initialised CLI project: there is no `config.toml`.

## Layout

| Path | What it holds |
|---|---|
| [migrations/](migrations/) | The finals schema: `20261020000000_finals_baseline.sql` builds it from empty, and later files change it |
| [tests/](tests/) | The SQL harness (`test_baseline.py`), `security_check.sql`, `supabase_stub.sql`, `probe_api.sh` |
| [../scripts/](../scripts/) | Live database tools: `backfill_content_hash.py` (fills `videos.content_sha256`) and `refresh_revision_embeddings.py` |
| [../archived/supabase/r2/](../archived/supabase/r2/) | Archived: `migrate_r2_names.py` and its test (one-off R2 rename) |
| [../archived/supabase/copy/](../archived/supabase/copy/) | Archived: `copy_midterm_to_finals.py` and `transform.sql`, the one-way midterm to finals copy. It targets the pre-revision schema, so do not run it |
| [../archived/supabase/midterm/](../archived/supabase/midterm/README.md) | Archived: the frozen midterm record, 14 migrations, `midterm_base_tables.sql`, freeze and unfreeze SQL |

## Test the schema

The harness needs no Supabase and no network. It runs on a throwaway local Postgres 16 with pgvector (`pgserver`), and `supabase_stub.sql` adds the API roles and Supabase's default grants, so the lockdown is tested against what a new project starts with.

```bash
cd supabase/tests
# Applies every file in ../migrations/ in order, then runs the security and behaviour tests
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py
```

## Build a new database

On an empty Supabase project, put its direct or session-pooler connection string in a file as `INCIDENT_DB_DSN` (for example `.env.local`) and run, from the profile folder:

```bash
./.scripts/setup-database.sh --env-file .env.local
```

It applies every file in `migrations/` in order, records the versions, runs `security_check.sql` and stops without applying anything if the target already has tables or recorded migrations. It does not use `supabase db push`, because two migrations share the version `20261028090000`, which the CLI cannot record on an empty database. Test it with `bash .scripts/test-setup-database.sh`.

## Add a finals migration

Finals uses the new key types: the server key is `sb_secret_...` and the public key `sb_publishable_...`, not JWTs. Send them in the `apikey` header only, as `probe_api.sh` does. The [Manage-database skill](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_) holds the connection test and the table of every key sender.

Add `migrations/YYYYMMDDHHMMSS_<what>.sql` after the baseline. Never edit an applied migration and never add files to `archived/supabase/midterm/`. In the same PR:
- extend `tests/test_baseline.py`, which applies every file in `migrations/` in order;
- give every new table RLS and every new function `SET search_path = ''`, or the harness and `security_check.sql` fail;
- update the [Data layer](../.docs/data.md).

The file must apply cleanly to a fresh database and to the live one: use `IF NOT EXISTS`, `CREATE OR REPLACE`, guarded `DO` blocks and conditional drops. After applying, run `security_check.sql` against finals. To record an out-of-band change without running SQL, use `supabase migration repair --workdir $W --db-url "$FINALS_DSN" --status applied <YYYYMMDDHHMMSS>`.

Apply a new file to finals **one file at a time**, not with `supabase db push`. Finals' history is not in step with `migrations/` (the two `20261028090000` files were applied by hand without history rows), so a plain `db push` would re-run them. The commands (apply with `psql`, record with `migration repair`, then `security_check.sql`) are in the [Manage-database skill](../skills/incident-manage-database/SKILL.md#apply-a-migration-to-finals). Once the history is repaired, `supabase db push --workdir $W --db-url "$FINALS_DSN" --dry-run` and then without `--dry-run` is the target state. `db push` at midterm fails ("remote migration versions not found") because midterm's history names versions that are no longer in `migrations/`; do not "fix" that with `migration repair` against midterm.

## Read more

- [Data layer: Supabase schema](../.docs/data.md#1-supabase-postgresql-schema): tables, functions, security and R2 keys
- [Architecture: Two Supabase projects](../.docs/architecture.md#two-supabase-projects-one-per-phase): which service points at which project
