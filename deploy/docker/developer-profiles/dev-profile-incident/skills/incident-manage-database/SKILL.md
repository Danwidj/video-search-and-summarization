---
name: incident-manage-database
description: Use to inspect or change the incident Supabase Postgres schema, write, test and apply a migration under supabase/migrations/, run the SQL harness or security check, build the finals database and copy midterm into it, query incident/review/ground-truth tables, or locate and validate video objects in Cloudflare R2. Not for running an analysis (use incident-analyze-video) or scoring ground truth (use incident-run-eval).
license: Apache-2.0
metadata:
  version: "0.2.0"
  profile: "dev-profile-incident"
  tags: "incident supabase postgres migration postgrest r2"
---
# Incident Manage Database

There is **one Supabase project per phase**:

- **Finals** is the live team database. There is no staging copy, so treat every write as production.
- **Midterm** (`rfevukimyftzbxlehwel`) is a frozen, read-only record. **Never write to it, push to it or apply anything to it**, apart from `supabase/midterm/freeze_midterm.sql` (once, at the cutover) or `unfreeze_midterm.sql` (rollback only).

Canonical facts: [`.docs/data.md`](../../.docs/data.md) (table specs, reviewer version and effective views, RPCs, cascades, security, R2 layout). Schema files and harness: [`supabase/README.md`](../../supabase/README.md). Which component points at which project: [`.docs/architecture.md`](../../.docs/architecture.md#two-supabase-projects-one-per-phase).

## Access routing

| Caller / network | Client | Credentials |
|---|---|---|
| Agent on `kwanz-ws` (port 5432 DPI-blocked) | PostgREST over HTTPS (`supabase-py`) | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` |
| `incident-console-v2` and `eval/` writers | PostgREST (console: adapters in `lib/adapters/supabase/` plus the not-yet-migrated callers listed in §7 of [`.docs/mvp2/console-hexagonal-architecture.md`](../../.docs/mvp2/console-hexagonal-architecture.md), all over `lib/postgrest/client.ts`; `eval/db_postgrest.py`) | same |
| Laptop tooling, `supabase` CLI, copy and parity scripts, v1 console | Direct Postgres | `INCIDENT_DB_DSN` (session pooler, 5432). Strip any `+psycopg2` suffix for the CLI. |

Only `service_role` and `postgres` reach anything: the public (`anon`) key is refused everywhere on finals, and on midterm after the freeze.

All PostgREST writers must use `/rpc/insert_incident` for the `incidents` + `review_status` pair. PostgREST has no client-held transactions.
The AI report rows (`incidents`, `entities`, `instruments`, `assets`) are never edited. Reviewer edits use `/rpc/save_human_report_edit` (or its `/rpc/apply_structured_report_edit` shim), which writes the run's reviewer version (`human_reports` and its items) and `review_status.edited_by/edited_at`, and sends a verified report back to `under review`. Every edited item must carry `source_id` (the AI item it came from, `null` for an added item); an edit without it is refused, never guessed. Status changes use `/rpc/set_review_status`; verifying without edits copies the AI report into the reviewer version. Neither touches `model_runs.notes` (the immutable analysis record). Readers that mean "the current report" use the `effective_*` views. Official reports are set only through `/rpc/select_official_report` / `/rpc/clear_official_report`.
The report library reads filtered, paginated metadata through the service-role-only `/rpc/list_incident_report_summaries`; its `p_entities`, `p_instruments`, and `p_assets` arrays filter the effective evidence by `(incident_id, model_run_id)`. It also takes `p_scope` (`all`/`official`), `p_entity_types`, `p_evidence_match` (`contains`/`exact`), and `p_timezone` (default `'UTC'`) for localised weekday and time-of-day filtering, and returns each report's analysis `outcome` and `isOfficial`. The library path does not read or sign video.
The operations dashboard reads bounded aggregates through the service-role-only `/rpc/get_incident_dashboard`, counting official incidents only and accepting `p_timezone` (default `'UTC'`) for local-time heatmap bucketing; it never downloads full report notes or evidence rows.
Natural-language search queries evidence items through the service-role-only `/rpc/search_evidence_items`, which performs a pgvector cosine distance search over `evidence_crops.embedding` strictly scoped to official reports (`videos.selected_model_run_id = ec.model_run_id`) and shows the reviewer's text; search hits and critic verification verdicts are logged into `query_results`.
`evidence_crops` is loaded by `scripts/backfill_official_timestamps.py` (remote VLM grounding and boxes, R2 upload, remote embeddings); rows are upserted, so rerunning is safe. Crops are keyed to AI items. The search route embeds queries with the same model, so a model change means re-embedding every row.
`model_runs` rows without an incident are normal: failed analysis attempts (`contract_failed` / `request_failed`) and runs whose report was deleted. Never count `model_runs` rows as analyses without filtering by `run_outcome(notes)`. PostgREST embeds between `videos` and `incidents` must name `incidents_incident_id_fkey` (two relationships).

## Rules

- **Migrations are the schema authority.** Finals is built by `supabase/migrations/20261020000000_finals_baseline.sql`; every change is a new timestamped file `supabase/migrations/YYYYMMDDHHMMSS_<what>.sql` after it. Never edit the baseline once finals has it, never add to `supabase/midterm/`, and never hand-edit the live DB without a matching migration file.
- **Test before applying:** extend and run the SQL harness (below) in the same PR. It applies every file in `supabase/migrations/` in order.
- **Dry-run first, then ask** before applying for real. Applying is live and shared.
- **After applying, run `supabase/tests/security_check.sql`** against finals: 0 rows expected.
- **Security on every new object:** RLS on every new table; `SET search_path = ''` and no `SECURITY DEFINER` on every function; nothing for `PUBLIC`/`anon`/`authenticated`. The harness and the security check fail otherwise. Default privileges only cover objects created by `postgres`.
- **Cascades are real.** Deleting a `videos` or `model_runs` row, or re-running `insert_incident` under the same `model_run_id`, cascades through the evidence, review, reviewer-version, notification and match tables. `insert_incident` refuses a run that has a reviewer version. Callers must re-insert evidence after the RPC.
- **Changing a function signature:** drop the old signature in the same migration. PostgREST rejects ambiguous overloads that share parameter names.
- **Never** print or commit the service-role key, public key or DSN. Backend code uses the service role server-side only.

## Instructions

### Run the SQL harness (no Supabase, no network)

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/supabase/tests
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py   # finals schema
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_freeze.py     # midterm freeze files
```

### Apply a migration to finals

From the repo root, with `FINALS_DSN` the finals session-pooler URL (after the cutover this is `INCIDENT_DB_DSN` in `.env.local`):

```bash
W=deploy/docker/developer-profiles/dev-profile-incident
supabase migration list --workdir $W --db-url "$FINALS_DSN"            # 1. local vs remote
supabase db push --workdir $W --db-url "$FINALS_DSN" --dry-run         # 2. preview, then ask captain/lead
supabase db push --workdir $W --db-url "$FINALS_DSN"                   # 3. apply
psql "$FINALS_DSN" -f $W/supabase/tests/security_check.sql             # 4. expect 0 rows
```

`db push` at midterm fails ("remote migration versions not found"), because midterm's history names versions that are no longer in `supabase/migrations/`. Do not "fix" that with `migration repair` against midterm.

To record an out-of-band change on finals without re-executing SQL:

```bash
supabase migration repair --workdir $W --db-url "$FINALS_DSN" --status applied <YYYYMMDDHHMMSS>
```

### Build finals and switch over (once)

People: someone with **Supabase account access** (the organisation owner who created midterm) creates the project and hands over its keys; someone with **`kwanz-ws` access** does the VM step; the captain applies the baseline and runs the copy. The cutover window is about 30 to 60 minutes, and nobody analyses, edits or verifies during it.

Preparation (no downtime):

1. **Supabase owner:** create the finals project in the same organisation and region as midterm, Postgres 17. Turn **off** email signups; keep SSL enforced. Hand over the URL, the server key, the session-pooler DSN and the public key (for the probe only) through the team's secret channel, never the repo. **Finals uses the new key types:** the server key is an `sb_secret_...` key and the public key an `sb_publishable_...` key. Neither is a JWT (see [Keys](#finals-keys-sb_secret_)), so every client that sends the key must accept that.
2. **Console and eval support (merged in PR 149):** the `incident-console-v2` and `eval/` change satisfies the three things finals needs: the console reads the `effective_*` views and changes status through `set_review_status`; **it sends `source_id` on every edited item** (`save_human_report_edit` refuses an edit without it, so the midterm console cannot edit on finals); and the console (`lib/postgrest/client.ts`) and eval (`eval/db_postgrest.py`) send an `sb_` key in `apikey` only, not as `Authorization: Bearer` (see [Keys](#finals-keys-sb_secret_)). Without it, every laptop console call at step 11 and the eval ground-truth read in the checklist fail.
3. **Captain:** apply the baseline (`db push --dry-run`, then for real, as above), then `security_check.sql` (0 rows) and `FINALS_URL=... FINALS_PUBLIC_KEY=... FINALS_SERVICE_KEY=... supabase/tests/probe_api.sh` (401/403 for every public-key line, 200 for the server key).
4. **VM key check** (someone with `kwanz-ws` access, before the cutover): the agent and the evidence loader connect through `supabase-py` (`utils/incident_db.py`, `acreate_client`), and `services/agent/pyproject.toml` only requires `supabase~=2.0` while `uv.lock` does not pin it, so the installed version on the VM is unknown. Test the agent's own environment against finals with the `sb_secret_` key (reads one row of `videos`; `rows 0` is a pass while finals is still empty):

   ```bash
   cd /srv/rise-up/vss
   read -rp 'finals URL: ' FINALS_URL; read -rsp 'finals sb_secret key: ' FINALS_KEY; echo; export FINALS_URL FINALS_KEY
   services/agent/.venv/bin/python -c "import os, importlib.metadata as m, supabase; c = supabase.create_client(os.environ['FINALS_URL'], os.environ['FINALS_KEY']); print('supabase', m.version('supabase'), 'ok, rows', len(c.table('videos').select('id').limit(1).execute().data))"
   unset FINALS_KEY
   ```

   If it fails with `Invalid API key`, a JWT error or a 401, upgrade in the agent's environment, `uv pip install --python services/agent/.venv/bin/python -U 'supabase>=2,<3'` (tell the team first: the VM is shared), then retest until it passes. The evidence loader (`scripts/backfill_official_timestamps.py`) runs with the same `services/agent/.venv` and connects through the same `incident_db.get_db()`, so this one test covers it too.
5. **Captain:** rehearse against the real finals: `supabase/copy/copy_midterm_to_finals.py --source-env <midterm env> --target-env <finals env> --not-edited m37883594f65802c8a31 --accept-item-edits mcd6cb9073218402f7bf` (rolls back; every check must pass). The guards added after the 2026-10-20 rehearsal (a stamped run with no reviewer version, a run naming a left-behind video) have only run on hand-made rows, so if one fires here, stop and decide the named runs by hand before going on.
   - **Manual stamp decision, known in advance:** a stamped legacy run stops the copy ("Runs keep an edit stamp but have no reviewer version"), because the midterm console rewrote `edited_by/at` with the verifier on every status change, so a stamp equal to the verification does not prove there was no edit. On 2026-10-20 (read only) exactly one run reaches it: **`m37883594f65802c8a31`** (legacy, official, verified; stamp = verification, `Presentation reviewer`, 2026-10-01 08:39:24). Its stored rows equal its legacy notes record, so it was not edited: pass `--not-edited m37883594f65802c8a31`.
   - **Accepted item edit, known in advance:** a contract run whose stored items differ from its notes record stops the copy ("Item-level reviewer edits found"). On 2026-10-21 exactly one does: **`mcd6cb9073218402f7bf`** (video `v5c609184047f88c720e`, official, verified), whose 2 entities and 3 assets were removed on midterm after 2026-10-20 outside the console. The captain chose to copy it as it is now: `--accept-item-edits mcd6cb9073218402f7bf` makes the stored items (none) its reviewer version, links each item to the AI item with identical content where unique (NULL otherwise, printed), and puts the AI items back from notes. The run is copied as it stands and keeps its midterm labels (verified, with its midterm stamp): the captain's call, since the removed items do not matter during development.
   - **How to decide any other run the error names:** compare its stored report (`incidents`, `entities`, `instruments`, `assets`) with what the AI wrote in its `model_runs.notes`; equal means `--not-edited <run>`, different means `--edited <run>` (the stored rows become the reviewer version; the AI's original text is lost). For a new run in "Item-level reviewer edits found", compare its stored items with the notes record and accept it with `--accept-item-edits <run>` only if the stored items are what should be kept.
   - **Then, every time:** run it once more with `--commit`, run `supabase/tests/parity_check.py` with the same arguments, and smoke-test a local console pointed at finals, read only. These rows are replaced at the cutover.

Cutover window:

6. Everyone stops local consoles and eval runs. No VM service has to stop.
7. **Freeze midterm:** run `supabase/midterm/freeze_midterm.sql` in the midterm SQL editor. Expect the check row `rls_off 0, anon_readable 0, service_reads true, service_writes false`.
8. **Captain:** `copy_midterm_to_finals.py --source-env <midterm env> --target-env <finals env> --not-edited m37883594f65802c8a31 --accept-item-edits mcd6cb9073218402f7bf --replace --commit` (plus any decision step 5 added). Keep its output as the record.
9. Re-check finals: `security_check.sql` (0 rows), `probe_api.sh`, `parity_check.py` (only the expected differences: uploaded videos 196 → 188 and without-report 55 → 47; 5 cleared `editedBy/editedAt`; the legacy official run `m37883594f65802c8a31` reads `assault` and `0`/`18`; 3 entity crops say `human`).
10. **VM:** back up `generated.env.remote`, set `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` (the `sb_secret_` key) to finals, restart `vss-agent` ([`incident-operate-vm`](../incident-operate-vm/SKILL.md)), and check the host (never the key) in `/proc/<pid>/environ`. If step 4 was not done, do it now, before the restart.
11. **Laptops:** set the 3 values in `.env.local`, refresh the `.env.local` copies in other worktrees, `git pull`, `./start.sh`.
12. Run the checklist below, announce that finals is live, and rewrite `.docs/status.md`.

Checklist:

- [ ] VM key check (step 4) passes in the agent's environment with the finals `sb_secret_` key.
- [ ] Security: `security_check.sql` 0 rows; `probe_api.sh` public key 401/403 on every table, view and RPC, server key 200; midterm refuses a server-key `POST /rest/v1/videos` and a public-key `GET`.
- [ ] Console (pointed at finals): `/api/health` 200 with `postgrest.reachable: true`; dashboard 13 official reports, uploaded 188, withOfficial 13, withoutReport 47, reviews 6 verified and 7 unreviewed; library 24 reports (13 official); `/reports/v18c252bf933457bc737?run=mb2484aa55750392701c` shows the reviewer's description; a video with failed attempts shows them in run history.
- [ ] On a test video: select and clear the official report; an edit leaves the AI row unchanged, adds a `human_reports` row whose items' `source_*_id` name their AI items, and bumps `revision`; verifying leaves `edited_by` unchanged; a second edit sends the report back to `under review`.
- [ ] Agent write (`./start.sh --mode vm`): one short clip in agent mode adds `model_runs`, `incidents`, `reports` and `review_status` rows on finals; midterm row counts unchanged.
- [ ] Search: `POST localhost:8000/api/v1/incidents/search {"query":"weapon","top_k":5}` returns hits with fetchable crop URLs, and **`queries` on finals grows** (the agent only warns when it cannot record a query, so a stale agent loses logs silently).
- [ ] Loader and eval: on `kwanz-ws`, `scripts/backfill_official_timestamps.py --dry-run` reads 13 official reports from finals; `eval` hermetic tests pass and a live ground-truth read finds 79 incidents.

Rollback:

- **Before step 10** (nothing points at finals yet): run `unfreeze_midterm.sql` and stop. Finals keeps its rows for the next attempt (`--replace`).
- **After step 10:** restore the backed-up `generated.env.remote` and restart the agent; put the midterm values back in `.env.local`; run `unfreeze_midterm.sql`; check out the console commit from before PR 149 (midterm has no effective views or `set_review_status`). The copy is one way: list anything written to finals after the cutover by `run_datetime` and `generated_datetime` and carry it back by hand.

After the switch, take a full `pg_dump` of midterm (Postgres 17 client, schema and data) for the course files. Pause midterm only when the finals phase is over; never delete it before the course ends.

### Read via PostgREST (works from anywhere with HTTPS)

```bash
curl -s "$INCIDENT_SUPABASE_URL/rest/v1/incidents?incident_id=eq.<id>&select=*" \
  -H "apikey: $INCIDENT_SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $INCIDENT_SUPABASE_SERVICE_ROLE_KEY"
```

With an `sb_secret_...` key (finals) send `apikey` only: drop the `Authorization` line.

### Finals keys (`sb_secret_`)

Finals has no legacy JWT keys: the server key is `sb_secret_...` and the public key `sb_publishable_...`. They are not JWTs, so the Supabase gateway rejects one sent as `Authorization: Bearer` ("invalid JWT"); send it in the `apikey` header only. Who sends the key, and whether it copes:

| Sender | How | Handles `sb_secret_`? |
|---|---|---|
| `vss-agent` (`utils/incident_db.py`, and through it `SupabaseSearchStore` and `SupabaseEvidenceStore`) | `supabase-py` `acreate_client` | Depends on the installed `supabase` version: `pyproject.toml` only requires `supabase~=2.0` and `uv.lock` does not pin it. Older 2.x releases validate the key as a JWT and raise `Invalid API key` (2.15.x still does; 2.18.0 and later do not). Prove it with the VM key check (step 4) |
| Evidence loader `scripts/backfill_official_timestamps.py` | Same `incident_db.get_db()` in the same `services/agent/.venv` | Same as the agent; the VM key check covers it. Its own `Authorization: Bearer` header goes to the VLM gateway, not Supabase |
| `mock-backend/base_profile_mock` (local mode) | Same `incident_db`, its own venv | Yes: its `uv.lock` pins `supabase` 2.31.0 |
| `incident-console-v2` `lib/postgrest/client.ts` | `apikey`; Bearer only for JWT-style (`eyJ...`) keys | Yes |
| `eval/db_postgrest.py` | `apikey`; Bearer only for JWT-style (`eyJ...`) keys | Yes |
| Retired `incident-console/db_postgrest.py` | `apikey` + always `Authorization: Bearer` | No (retired; do not point it at finals) |
| `supabase/tests/probe_api.sh` | `apikey`; Bearer only for `eyJ...` keys | Yes |
| `supabase/copy/`, `parity_check.py`, `supabase` CLI | Direct DSN, no key | Not affected |

Follow-ups (not in this change): pin a minimum `supabase` version in `services/agent/pyproject.toml` and lock it in `uv.lock`.

### R2 objects

- **One bucket for both phases:** finals and the midterm record name the same keys; nothing was copied. A delete in finals also removes the object the midterm record names.
- **Keys:** all new user uploads go to `uploads/<encodeURIComponent(sensorId)>/<uuid><ext>` in both modes. Classified seed/evaluation clips remain under `anomaly/<category>/<file>`.
- **Valid keys** (per `isValidR2Key`): not absolute, no `.`/`..` prefix. VST `./streamer/media/...` paths are not keys.
- **Durability check:** `verifyR2Video` uses `HeadObject`; direct uploads require an exact nonzero byte-length match, and analysis requires a nonempty object before inference.
- **Playback** is by 1-hour presigned GET only. The bucket is private.
- **Report-card thumbnails:** new uploads use `thumbnails/<video-key>.webp`, derived by `thumbnailKeyForVideo`; legacy videos may have no thumbnail and use the UI skeleton. Deleting a video deletes this derived object too.

## After changing anything

In the same PR:
- Extend `supabase/tests/test_baseline.py` for the new behaviour.
- Update the table specs in [`.docs/data.md`](../../.docs/data.md).
- Update [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md) if report fields moved.
- Update [`.docs/status.md`](../../.docs/status.md) if the migration was applied live.
- Add a [`.docs/decisions.md`](../../.docs/decisions.md) entry for any schema decision.
