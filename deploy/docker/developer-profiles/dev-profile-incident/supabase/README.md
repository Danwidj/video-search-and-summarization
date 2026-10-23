# Supabase schema — dev-profile-incident

There is one Supabase project per project phase:

| Project | Role | Schema source |
|---|---|---|
| **Finals** (new project) | Live database for every service | [`migrations/`](migrations/): one baseline file, then any later finals migration |
| **Midterm** (`rfevukimyftzbxlehwel`) | Frozen, read-only record | [`midterm/`](midterm/README.md): the 14 midterm migrations, archived. **Never push** |

The decision and its reasons: [`../.docs/decisions.md`](../.docs/decisions.md) ("One Supabase
project per phase"). Table and RPC reference: [`../.docs/data.md`](../.docs/data.md).

This directory is the `--workdir` target of the `supabase` CLI
(`--workdir deploy/docker/developer-profiles/dev-profile-incident`, which reads
`supabase/migrations/`). It is not a fully initialised CLI project: there is no `config.toml`, and
nobody runs `supabase init`/`link` here. `supabase db push --workdir <dir> --db-url <url>` works
against a bare `migrations/` folder.

## Layout

```
supabase/
  migrations/   20261020000000_finals_baseline.sql — builds finals from empty
                20261022123252_drop_unused_tables.sql — removes tables no live code uses
                20261023000000_report_revisions_schema.sql — versioned JSONB reports
                20261023000100_report_revisions_functions.sql — revision RPCs
                20261023000200_searchable_latest_revision.sql — crops for the newest revision, official_since, card fields
  tests/        SQL harness (test_baseline.py, test_freeze.py), security_check.sql, supabase_stub.sql,
                parity_check.py, rehearse.py, probe_api.sh
  copy/         copy_midterm_to_finals.py + transform.sql: the one-way midterm -> finals copy (historical)
  midterm/      frozen midterm record: migrations/ (14), midterm_base_tables.sql, freeze/unfreeze SQL
```

## Current finals schema

The migrations build the original midterm-shaped model, drop the tables no live code uses, then
replace the relational report model with versioned snapshots. The **current** schema has six tables:

- `videos` — upload registry, now with `official_revision_id` (composite FK to one of its own
  revisions) and `official_since` (when it was marked); the old `selected_model_run_id`/`selected_by`/`selected_at` columns are gone.
- `queries`, `model_runs` — unchanged search audit and run registry. Model runs keep the immutable
  analysis-attempt record in `notes`.
- `report_revisions` — append-only `ai`/`human` snapshots: full contract report in `payload`,
  evidence list in `evidence`, plain facets (`incident_type`, `severity_level`, timestamps), and
  links to the video (`revision_no` per video), run (`model_run_id`) and parent revision
  (`parent_id`).
- `evidence_crops` — searchable crops keyed by `revision_id` with the pgvector embedding; rows belong
  to the video's **searchable revision**: the official one, else the newest.
- `query_results` — search audit keyed by `query_id` and `revision_id`.

`incidents`, `reports`, `entities`, `instruments`, `assets`, `human_reports*`, `review_status`,
`gt_*` and `severity_eval_log`, and the functions that read them, are gone. Every report read goes
through `report_revisions`, directly or via the library/dashboard RPCs. Details, columns and
constraints: [`../.docs/data.md`](../.docs/data.md).

### Functions

- `save_human_revision` — atomically appends a human revision (`max(revision_no)+1`, inherits the
  parent's run) and returns its JSON descriptor.
- `set_official_revision` — in one transaction sets `videos.official_revision_id` and
  `official_since` and moves the video's `evidence_crops` to the new official revision (the caller's
  crop list, or the rows it already has); NULL clears the pointer and leaves the newest revision
  searchable.
- `set_revision_crops` — stores the crops of the video's searchable revision (official, else newest)
  without changing the pointer; refused for any other revision.
- `search_evidence_items` — HNSW cosine search over each video's searchable revision, returning the
  incident, revision, run, facets and similarity.
- `list_incident_report_summaries` — one card per video (official, else newest), filtered by
  `p_kind` (`ai`/`human`), type, severity, evidence and text; cards carry `officialSince`,
  `versionCount`, `evidenceCount` and `thumbnail`.
- `get_incident_dashboard` — aggregates official revisions only.

Every function is `SECURITY INVOKER`, pins `SET search_path = ''`, and is executable by
`service_role` only.

### Security

RLS is on for all six tables with no policies. Default privileges are set before any object is
created, so `PUBLIC`/`anon`/`authenticated` get nothing on tables, sequences, views or functions;
`service_role` gets everything. A self-check block in the baseline **fails the migration** if a table
has RLS off, anything is exposed, or any function is `SECURITY DEFINER` or lacks a fixed
`search_path`. Run `tests/security_check.sql` after every applied migration (expect 0 rows), and
`tests/probe_api.sh` to confirm over REST that the public key is refused.

## Tests (no Supabase, no network)

The harness runs on a throwaway local Postgres (`pgserver`: Postgres 16 + pgvector).
`tests/supabase_stub.sql` adds the Supabase API roles and **Supabase's default grants to
anon/authenticated**, so the lockdown is tested against what a new project starts with.

```bash
cd supabase/tests
# Finals schema: applies every file in ../migrations/ in order; 16 tests (security and behaviour)
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py
# Midterm freeze/unfreeze on a local replica of midterm
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_freeze.py
```

`tests/rehearse.py <midterm env file>` is the historical cutover rehearsal (local Postgres → baseline
→ copy from midterm, read only → security audit → reader parity → re-copy with `--replace`). It
predates the revision migration, needs the midterm DSN and writes only to the local Postgres.

## Building finals

The schema push and copy commands are below; what points at which project is in
[`../.docs/architecture.md`](../.docs/architecture.md#two-supabase-projects-one-per-phase). In short, with `FINALS_DSN` the finals session-pooler URL (port
5432, plain `postgresql://`, no SQLAlchemy suffix):

```bash
W=deploy/docker/developer-profiles/dev-profile-incident   # run from the repo root
supabase db push --workdir $W --db-url "$FINALS_DSN" --dry-run
supabase db push --workdir $W --db-url "$FINALS_DSN"
psql "$FINALS_DSN" -f $W/supabase/tests/security_check.sql    # expect 0 rows
FINALS_URL=... FINALS_PUBLIC_KEY=... FINALS_SERVICE_KEY=... $W/supabase/tests/probe_api.sh
                                       # expect 401/403 for every public-key line, 200 for the service key
```

**Finals uses the new key types:** the server key is `sb_secret_...` and the public key
`sb_publishable_...`, not JWTs. They go in the `apikey` header only (`probe_api.sh` does this).
Before the switch, the VM's `supabase-py` must be proven to accept the `sb_secret_` key (the
agent's version is not pinned and older 2.x releases reject non-JWT keys), and the console and
eval stop sending the key as `Authorization: Bearer` (merged in PR 149). The connection test and the
table of every key sender are in the
[`incident-manage-database`](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_)
skill.

The one-way midterm → finals copy in [`copy/`](copy/) was used for the original cutover and is kept
for the record. It targets the pre-revision schema; do not run it against the current finals schema.
Its design and the per-run decisions are in [`copy/README.md`](copy/README.md) and the copy script.
R2 objects were never copied: same bucket, same keys.

## Adding a finals migration

Add `migrations/YYYYMMDDHHMMSS_<what>.sql` after the baseline, never edit an applied migration, and
never add files to `midterm/`. In the same PR:

- extend `tests/test_baseline.py` (it applies every file in `migrations/` in order);
- give every new table RLS and every new function `SET search_path = ''` (the harness and
  `security_check.sql` fail otherwise);
- update [`../.docs/data.md`](../.docs/data.md);
- after applying, run `tests/security_check.sql` against finals (expect 0 rows).

Migrations must be safe on the live database, which already has the revision schema: use
`IF NOT EXISTS`, `CREATE OR REPLACE`, guarded `DO` blocks and conditional drops so the same file
applies cleanly to a fresh database and to the existing one. `tests/test_baseline.py` reapplies the
revision migrations on the built schema to prove this.

Applying to the live database is "ask first" (profile [`AGENTS.md`](../AGENTS.md)). To record an
out-of-band change without running SQL:

```bash
supabase migration repair --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$FINALS_DSN" --status applied <YYYYMMDDHHMMSS>
```
