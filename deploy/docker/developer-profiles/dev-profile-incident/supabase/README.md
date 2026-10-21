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
  migrations/   20261020000000_finals_baseline.sql — builds finals from empty; later finals migrations follow it
  tests/        SQL harness (test_baseline.py, test_freeze.py), security_check.sql, supabase_stub.sql,
                parity_check.py, rehearse.py, probe_api.sh
  copy/         copy_midterm_to_finals.py + transform.sql: the one-way midterm -> finals copy
  midterm/      frozen midterm record: migrations/ (14), midterm_base_tables.sql, freeze/unfreeze SQL
```

## The finals baseline

[`migrations/20261020000000_finals_baseline.sql`](migrations/20261020000000_finals_baseline.sql)
builds the whole incident schema in one transaction:

1. **pgvector in `extensions`**, not `public`, so none of its functions become REST RPCs.
2. **Default privileges first:** before any object exists, nothing new in `public` is granted to
   `anon`/`authenticated`, and new functions get no `EXECUTE` for `PUBLIC`.
3. **The 20 operational, evaluation and search tables** exactly as on midterm, with midterm's
   constraint names (PostgREST embed hints such as `incidents_incident_id_fkey` depend on them).
   The four pre-v1 tables (`incident_reports`, `incident_entities`, `incident_instruments`,
   `incident_assets`) are not created.
4. **The reviewer version of a report** (`human_reports`, `human_report_entities`,
   `human_report_instruments`, `human_report_assets`) next to the immutable AI rows, and the
   `effective_incidents/entities/instruments/assets` views (reviewer version if there is one,
   else the AI one; same columns as the AI tables, plus `source_*_id` and `source`).
5. **Every function still called**, each with `SET search_path = ''`: `insert_incident` (same
   signature; refuses to re-run a run that has a reviewer version), the library, dashboard and
   search RPCs (reading the effective views), official selection, and the reviewer RPCs
   `create_human_report_from_ai`, `save_human_report_edit`, `set_review_status` and the
   `apply_structured_report_edit` compatibility shim. `apply_incident_report_patch` and
   `replace_incident_evidence` are gone.
6. **Security:** RLS on all 24 tables, nothing for `PUBLIC`/`anon`/`authenticated`, everything for
   `service_role`, views read-only. A self-check block **fails the migration** if anything is still
   exposed, any function is `SECURITY DEFINER`, or any function lacks a fixed `search_path`.

`insert_incident` is live code: every PostgREST writer (the agent's `utils/incident_db.py`,
`eval/db_postgrest.py`, the console) calls `/rpc/insert_incident`, because PostgREST has no
client-held transactions.

## Tests (no Supabase, no network)

The harness runs on a throwaway local Postgres (`pgserver`: Postgres 16 + pgvector).
`tests/supabase_stub.sql` adds the Supabase API roles and **Supabase's default grants to
anon/authenticated**, so the lockdown is tested against what a new project starts with.

```bash
cd supabase/tests
# Finals schema: applies every file in ../migrations/ in order, 24 tests (security, behaviour and the copy's guards)
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py
# Midterm freeze/unfreeze on a local replica of midterm
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_freeze.py
```

`tests/rehearse.py <midterm env file>` is the full rehearsal (local Postgres → baseline → copy from
midterm, read only → security audit → reader parity → re-copy with `--replace`). It needs the
midterm DSN; it writes only to the local Postgres.

## Building finals (cutover)

The full order of steps, the checklist and the rollback are in the
[`incident-manage-database`](../skills/incident-manage-database/SKILL.md) skill; what points at
which project is in [`../.docs/architecture.md`](../.docs/architecture.md#two-supabase-projects-one-per-phase). In short, with `FINALS_DSN` the finals session-pooler URL (port
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
eval must stop sending the key as `Authorization: Bearer` (PR B). The connection test and the
table of every key sender are in the
[`incident-manage-database`](../skills/incident-manage-database/SKILL.md#finals-keys-sb_secret_)
skill.

Then the copy, from a laptop (`kwanz-ws` blocks port 5432). Each env file holds `INCIDENT_DB_DSN`:

```bash
cd $W/supabase/copy
uv run --no-project --with 'psycopg[binary]' python copy_midterm_to_finals.py \
  --source-env <midterm env file> --target-env <finals env file> \
  --not-edited m37883594f65802c8a31 --accept-item-edits mcd6cb9073218402f7bf   # rehearsal: rolls back
uv run --no-project --with 'psycopg[binary]' python copy_midterm_to_finals.py \
  --source-env <midterm env file> --target-env <finals env file> \
  --not-edited m37883594f65802c8a31 --accept-item-edits mcd6cb9073218402f7bf \
  --replace --commit                                                         # at cutover
cd ../tests && uv run --no-project --with 'psycopg[binary]' python parity_check.py \
  --source-env <midterm env file> --target-env <finals env file>
```

The copy reads midterm in one `REPEATABLE READ READ ONLY` transaction and writes finals in one
transaction: rows are streamed into temp tables, [`copy/transform.sql`](copy/transform.sql) builds
the finals rows, and every check runs (row counts, checksums of every untouched column, official
selections, labels, reviewer versions, AI rows equal to `model_runs.notes`). Any failed check, or
no `--commit`, rolls back. It refuses a finals database that already has rows unless `--replace`
(before go-live only).

What it copies and what it leaves behind:

- **Copies** every real video, run, report, review and official selection; evidence crops with
  their embeddings; query logs and search results; ground truth (`gt_*`, `*_matches`); evaluation
  data (`P1-*` runs, `severity_eval_log`); and the seed/fake test reports (`MR-SEED`, `MOCK8`).
- **Leaves behind** 20 orphan runs whose video was deleted, 15 unlinked test runs (`mock-run-*`,
  `nmtest0925a`), 8 broken uploads (no incident, ground truth, attempt or playable file) and the
  4 pre-v1 tables. Guards fail the copy if anything else matches those rules, if a run that
  names a left-behind video in its notes would be copied, if an edit changed items (their AI
  source is a guess), or if a run keeps an edit stamp but gets no reviewer version: a person
  decides each of those by hand.
- **Item edits are accepted per run.** A contract run whose stored items differ from its notes
  record stops the copy. After checking it, rerun with `--accept-item-edits <run>`: its stored
  items become the reviewer version, each linked to the AI item with identical content where that
  match is unique (no link otherwise: that item shows no crop), and the changed kinds' AI items
  are put back from notes. The script prints every link it made or left empty. It refuses a run
  that has evidence crops or eval matches (they would need re-keying). On 2026-10-21 one run reached this:
  `mcd6cb9073218402f7bf` (video `v5c609184047f88c720e`, official, verified). Its 2 entities and
  3 assets were removed from midterm after 2026-10-20 (not through the console: its review stamp
  is still the 2026-10-01 verification), and the captain chose to copy it as it is now. So its
  reviewer version has no items, and its AI items come back from notes. It is copied as it stands
  and keeps its midterm labels (verified, with its midterm stamp), by the captain's call that the
  removed items do not matter during development.
- **Legacy edit stamps are a person's call.** On a legacy (non-contract) run nothing records what
  the AI wrote, and the midterm console rewrote `edited_by/at` with the verifier on every status
  change, so a stamp equal to the verification proves nothing. Such a run stops the copy, naming
  itself; rerun with `--not-edited <run>` (clear the stamp; a verified run then gets a copy of its
  rows "verified as the AI wrote it") or `--edited <run>` (its stored rows become the reviewer
  version, kept stamp and all; the AI original is lost). On 2026-10-20 one run reached this:
  `m37883594f65802c8a31` (legacy, official, verified; stamp = verification, Presentation reviewer,
  2026-10-01 08:39:24). Its stored rows equal its legacy notes record, so it was not edited:
  `--not-edited m37883594f65802c8a31`. A new name in the error means midterm changed: compare that
  run's stored report with its `model_runs.notes` before choosing.
- **Changes on the way:** `fighting` → `assault`, `animal` → `animal attack`, `person` → `human`
  (incidents, entities and entity crop names); a reviewer version for the 3 edited and 6 verified
  reports (7 in all), with the AI's own text or items put back on the 3 edited runs from
  `model_runs.notes`; 5 misleading `review_status.edited_by/at` stamps (status changes, not edits)
  cleared: 4 proven by the rows (contract runs equal to their notes record) and 1 by the
  `--not-edited` decision (rehearsal of 2026-10-21).

R2 objects stay where they are: same bucket, same keys, nothing to copy.

## Adding a finals migration

Add `migrations/YYYYMMDDHHMMSS_<what>.sql` after the baseline, never edit the baseline once it is
applied to finals, and never add files to `midterm/`. In the same PR:

- extend `tests/test_baseline.py` (it applies every file in `migrations/` in order);
- give every new table RLS and every new function `SET search_path = ''` (the harness and
  `security_check.sql` fail otherwise);
- update [`../.docs/data.md`](../.docs/data.md);
- after applying, run `tests/security_check.sql` against finals (expect 0 rows).

Applying to the live database is "ask first" (profile [`AGENTS.md`](../AGENTS.md)). To record an
out-of-band change without running SQL:

```bash
supabase migration repair --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$FINALS_DSN" --status applied <YYYYMMDDHHMMSS>
```
