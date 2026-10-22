---
name: incident-manage-database
description: Use to inspect or change the incident Supabase Postgres schema, write, test and apply a migration under supabase/migrations/, run the SQL harness or security check, query incident/review/ground-truth tables, or locate and validate video objects in Cloudflare R2. Not for running an analysis (use incident-analyze-video), searching evidence (use incident-search), or scoring ground truth (use incident-run-eval).
license: Apache-2.0
metadata:
  version: "0.2.1"
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
| `mock-backend/base_profile_mock` (mock mode) | Same `incident_db`, its own venv | Yes: its `uv.lock` pins `supabase` 2.31.0 |
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
