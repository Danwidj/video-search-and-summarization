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
The AI report rows (`incidents`, `entities`, `instruments`, `assets`) are never edited. Reviewer edits use `/rpc/save_human_report_edit` (or its `/rpc/apply_structured_report_edit` shim), which writes the run's reviewer version (`human_reports` and its items) and `review_status.edited_by/edited_at`, and sends a verified report back to `under review`. Status changes use `/rpc/set_review_status`; verifying without edits copies the AI report into the reviewer version. Neither touches `model_runs.notes` (the immutable analysis record). Readers that mean "the current report" use the `effective_*` views. Official reports are set only through `/rpc/select_official_report` / `/rpc/clear_official_report`.
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

1. **Supabase owner:** create the finals project in the same organisation and region as midterm, Postgres 17. Turn **off** email signups; keep SSL enforced. Hand over the URL, the server key, the session-pooler DSN and the public key (for the probe only) through the team's secret channel, never the repo.
2. Merge the console change that reads the effective views and `set_review_status` (it must be in before the switch).
3. **Captain:** apply the baseline (`db push --dry-run`, then for real, as above), then `security_check.sql` (0 rows) and `FINALS_URL=... FINALS_PUBLIC_KEY=... FINALS_SERVICE_KEY=... supabase/tests/probe_api.sh` (401/403 for every public-key line, 200 for the server key).
4. **Captain:** rehearse against the real finals: `supabase/copy/copy_midterm_to_finals.py --source-env <midterm env> --target-env <finals env>` (rolls back; every check must pass). Then once with `--commit`, run `supabase/tests/parity_check.py` with the same arguments, and smoke-test a local console pointed at finals, read only. These rows are replaced at the cutover.

Cutover window:

5. Everyone stops local consoles and eval runs. No VM service has to stop.
6. **Freeze midterm:** run `supabase/midterm/freeze_midterm.sql` in the midterm SQL editor. Expect the check row `rls_off 0, anon_readable 0, service_reads true, service_writes false`.
7. **Captain:** `copy_midterm_to_finals.py --source-env <midterm env> --target-env <finals env> --replace --commit`. Keep its output as the record.
8. Re-check finals: `security_check.sql` (0 rows), `probe_api.sh`, `parity_check.py` (only the expected differences: uploaded videos 196 → 188 and without-report 55 → 47; 6 cleared `editedBy/editedAt`; the legacy official run `m37883594f65802c8a31` reads `assault` and `0`/`18`; 3 entity crops say `human`).
9. **VM:** back up `generated.env.remote`, set `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` to finals, restart `vss-agent` ([`incident-operate-vm`](../incident-operate-vm/SKILL.md)), and check the host (never the key) in `/proc/<pid>/environ`.
10. **Laptops:** set the 3 values in `.env.local`, refresh the `.env.local` copies in other worktrees, `git pull`, `./start.sh`.
11. Run the checklist below, announce that finals is live, and rewrite `.docs/status.md`.

Checklist:

- [ ] Security: `security_check.sql` 0 rows; `probe_api.sh` public key 401/403 on every table, view and RPC, server key 200; midterm refuses a server-key `POST /rest/v1/videos` and a public-key `GET`.
- [ ] Console (pointed at finals): `/api/health` 200 with `postgrest.reachable: true`; dashboard 13 official reports, uploaded 188, withOfficial 13, withoutReport 47, reviews 6 verified and 7 unreviewed; library 24 reports (13 official); `/reports/v18c252bf933457bc737?run=mb2484aa55750392701c` shows the reviewer's description; a video with failed attempts shows them in run history.
- [ ] On a test video: select and clear the official report; an edit leaves the AI row unchanged, adds a `human_reports` row and bumps `revision`; verifying leaves `edited_by` unchanged; a second edit sends the report back to `under review`.
- [ ] Agent write (`./start.sh --mode vm`): one short clip in agent mode adds `model_runs`, `incidents`, `reports` and `review_status` rows on finals; midterm row counts unchanged.
- [ ] Search: `POST localhost:8000/api/v1/incidents/search {"query":"weapon","top_k":5}` returns hits with fetchable crop URLs, and **`queries` on finals grows** (the agent only warns when it cannot record a query, so a stale agent loses logs silently).
- [ ] Loader and eval: on `kwanz-ws`, `scripts/backfill_official_timestamps.py --dry-run` reads 13 official reports from finals; `eval` hermetic tests pass and a live ground-truth read finds 79 incidents.

Rollback:

- **Before step 9** (nothing points at finals yet): run `unfreeze_midterm.sql` and stop. Finals keeps its rows for the next attempt (`--replace`).
- **After step 9:** restore the backed-up `generated.env.remote` and restart the agent; put the midterm values back in `.env.local`; run `unfreeze_midterm.sql`; check out the console commit from before the effective-views change (midterm has no effective views or `set_review_status`). The copy is one way: list anything written to finals after the cutover by `run_datetime` and `generated_datetime` and carry it back by hand.

After the switch, take a full `pg_dump` of midterm (Postgres 17 client, schema and data) for the course files. Pause midterm only when the finals phase is over; never delete it before the course ends.

### Read via PostgREST (works from anywhere with HTTPS)

```bash
curl -s "$INCIDENT_SUPABASE_URL/rest/v1/incidents?incident_id=eq.<id>&select=*" \
  -H "apikey: $INCIDENT_SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $INCIDENT_SUPABASE_SERVICE_ROLE_KEY"
```

A new-style `sb_secret_...` key goes in `apikey` only: it is not a JWT, so PostgREST rejects it as `Authorization: Bearer`.

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
