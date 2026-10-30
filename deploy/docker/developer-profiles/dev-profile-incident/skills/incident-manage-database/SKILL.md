---
name: incident-manage-database
description: Use to inspect or change the incident Supabase Postgres schema, write, test and apply a migration under supabase/migrations/, run the SQL harness or security check, query incident/review tables, or locate and validate video objects in Cloudflare R2. Not for running an analysis (use incident-analyze-video) or searching evidence (use incident-search).
license: Apache-2.0
metadata:
  version: "0.3.0"
  profile: "dev-profile-incident"
  tags: "incident supabase postgres migration postgrest r2"
---
# Incident Manage Database

There is **one Supabase project per phase**:

- **Finals** is the live team database. There is no staging copy, so treat every write as production.
- **Midterm** (`rfevukimyftzbxlehwel`) is a frozen, read-only record. **Never write to it, push to it or apply anything to it**, apart from `supabase/midterm/freeze_midterm.sql` (once, at the cutover) or `unfreeze_midterm.sql` (rollback only).

Canonical facts: [`.docs/data.md`](../../.docs/data.md) (table specs, report revisions, RPCs, cascades, security, R2 layout). Schema files and harness: [`supabase/README.md`](../../supabase/README.md). Which component points at which project: [`.docs/architecture.md`](../../.docs/architecture.md#two-supabase-projects-one-per-phase).

## Access routing

| Caller / network | Client | Credentials |
|---|---|---|
| Agent on `kwanz-ws` (port 5432 DPI-blocked) | PostgREST over HTTPS (`supabase-py`) | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` |
| `incident-console-v2` and `eval/` writers | PostgREST (console: the adapters in `src/modules/*/infrastructure/supabase/` over `src/lib/postgrest/client.ts`, see [`.docs/mvp2/console-hexagonal-architecture.md`](../../.docs/mvp2/console-hexagonal-architecture.md); `eval/db_postgrest.py`) | same |
| Laptop tooling, `supabase` CLI, copy and parity scripts | Direct Postgres | `INCIDENT_DB_DSN` (session pooler, 5432). Strip any `+psycopg2` suffix for the CLI. |

Only `service_role` and `postgres` reach anything: the public (`anon`) key is refused everywhere on finals, and on midterm after the freeze.

The mvp3 model groups videos into **incidents**: several videos belong to one incident (`videos.incident_id`) with one combined report. Video ids are real file names (`TEXT`), model-run ids are readable (`<subject>@<UTC timestamp>`), nothing is hashed. This applies to a **new empty database**; the mvp3 migrations are never applied to finals.
Each video is analysed once: the agent appends one `video_analyses` row (`insert_video_analysis`; unchanged contract report, evidence, facets, summary vector; the latest row per video wins). A report is rebuilt from stored analyses by `/rpc/create_ai_revision(p_incident_id, p_model_run_id, p_note, p_payload, p_evidence, p_video_names, p_incident_type, p_severity_level, [p_start_seconds, p_end_seconds, p_embedding])`, which locks the incident, appends a `kind='ai'` revision (`revision_no = max + 1`, `parent_id` NULL, `video_names` = covered videos, all current videos of the incident) and copies each covered video's newest crops onto it. `payload` is an envelope `{overview, cameras:[{video, report}]}`. The agent no longer writes revisions or `videos` (`IncidentDB` reads them).
A reviewer edit calls `/rpc/save_human_revision_with_crops(p_incident_id, p_parent_id, p_created_by, p_note, p_payload, p_evidence, p_incident_type, p_severity_level, p_start_seconds, p_end_seconds, p_crops)` (`kind='human'`, the parent must be in the same incident, inherits the run and the parent's `video_names`; it wraps `save_human_revision` and stores the crops for the new revision only, each crop's `video_id` a current video of the incident and in the revision's `video_names`). No revision is ever edited or deleted, and the append-only trigger enforces that; only the delete of the whole incident cascades to its revisions.
`incidents.official_revision_id` names the one official revision per incident (composite FK `(id, official_revision_id)` to that incident's revision). Select it only through `/rpc/set_official_revision(p_incident_id, p_revision_id)`, which sets the pointer and `official_since` (NULL clears; the same revision again keeps `official_since`). It moves **no crops**: the searchable revision of an incident (official, else newest; `searchable_revision_id`) keeps its `evidence_crops` through `/rpc/set_revision_crops(p_incident_id, p_revision_id, p_crops)` (refused for any other revision; each crop names its `video_id`) or `/rpc/replace_video_crops(p_incident_id, p_video_id, p_revision_id, p_crops)` for one video. Never write `report_revisions`, `incidents.official_revision_id` or `evidence_crops` by hand.
Incident operations: `/rpc/merge_incidents(p_target_incident_id, p_source_incident_id)` moves the source's videos into the target and deletes the source incident (its revisions, crops and suggestions go; the target's revisions stay and show "Does not include" until regenerated). `/rpc/remove_video(p_video_id, p_mode)` with `'delete'` removes the video, its analyses and crops (revisions stay as history; the last video deletes the incident) or `'move'` splits it into a new incident (refused for the last video). Both return the R2 keys to clean up (`orphaned_crop_images`, `deleted_crop_images`, `deleted_video_key`). `/rpc/auto_merge_incidents(p_target_incident_id, p_source_incident_id, p_score, p_reasons)` is the same merge that also stamps the moved videos' `auto_joined_score/_reasons/_at` (the record of an automatic join, which survives the merge deleting the suggestion row); `remove_video` 'move' clears it. Matching: `/rpc/shortlist_similar_incidents(p_video_id, p_limit, p_min_similarity)` picks candidate incidents by cosine similarity of latest-analysis embeddings; `record_match_suggestion(p_incident_a_id, p_incident_b_id, p_score, p_reasons)` and `reject_match_suggestion(p_suggestion_id)` write `incident_match_suggestions` (one row per unordered pair; the system joins at 0.5 or more by itself and records it per video; below that the reviewer decides).
The report library reads filtered, paginated metadata through the service-role-only `/rpc/list_incident_report_summaries`: **one card per incident** (official revision, else newest; an incident with no revision still has a card with a null `revisionId`). The filter arguments are unchanged (`p_search` also matches video names, `p_entities`, `p_instruments`, `p_assets`, `p_kind`, `p_scope`, `p_entity_types`, `p_evidence_match`, `p_timezone` default `'UTC'`). Each card has `incidentId`, `revisionId`, `revisionNo`, `kind`, `outcome`, `isOfficial`, `officialSince`, `versionCount`, `videoCount`, `firstVideoName`, `firstVideoKey`, `thumbnail` (the earliest video's), `sensorId`, `coverage`, `missingVideos` and `removedVideos`; there is no `evidenceCount`. The library path does not read or sign video.
The operations dashboard reads bounded aggregates through the service-role-only `/rpc/get_incident_dashboard`, counting each incident's official revision only (`total`, `incidents {total, withOfficial, awaitingSelection, withoutReport}`, `videos {uploaded}`) and accepting `p_timezone` (default `'UTC'`); it never downloads full report notes or evidence rows.
Natural-language search queries evidence items through the service-role-only `/rpc/search_evidence_items` (9 arguments), a pgvector cosine search over `evidence_crops.embedding` scoped to each incident's searchable revision. Hits return `incident_id`, `revision_id`, the source `video_id` and `video_filepath`, and the query and hits (with critic verdicts, `unverified` while the critic is off) are logged into `query_results` against the revision. The optional `p_video_id` and `p_incident_id` scope the scan; a NULL embedding with a scope lists the crops in time order (migrations `20261028090100_search_evidence_items_video_id.sql`, replaced by `20261030140000_incident_search.sql`).
`report_revisions.embedding` (1024) holds an AI revision's summary vector, written by `create_ai_revision`; `search_report_revisions` searches it (one hit per incident, on its searchable revision; human revisions have NULL). `evidence_crops` is written by `save_human_revision_with_crops`, `create_ai_revision` (copy), `set_revision_crops` and `replace_video_crops` from the crop list the console sends (the agent returns the embeddings via `POST /api/v1/incidents/evidence-embeddings`; it does not write the rows). The search route embeds queries with the same model, so a model change means re-embedding every row. `video_analyses.embedding` feeds the matching shortlist.
`model_runs` rows without an analysis or revision are normal: failed analysis attempts (`contract_failed` / `request_failed`). Never count `model_runs` rows as analyses without filtering by `run_outcome(notes)`.
The console and agent flows that call these functions are still landing (mvp3 Phases 4 and 5); the database side is as above.

## Rules

- **Migrations are the schema authority.** Finals is built by `supabase/migrations/20261020000000_finals_baseline.sql`; every change is a new timestamped file `supabase/migrations/YYYYMMDDHHMMSS_<what>.sql` after it. Never edit the baseline once finals has it, never add to `supabase/midterm/`, and never hand-edit the live DB without a matching migration file.
- **Test before applying:** extend and run the SQL harness (below) in the same PR. It applies every file in `supabase/migrations/` in order.
- **Dry-run first, then ask** before applying for real. Applying is live and shared.
- **After applying, run `supabase/tests/security_check.sql`** against finals: 0 rows expected.
- **Security on every new object:** RLS on every new table; `SET search_path = ''` and no `SECURITY DEFINER` on every function; nothing for `PUBLIC`/`anon`/`authenticated`. The harness and the security check fail otherwise. Default privileges only cover objects created by `postgres`.
- **Cascades are real.** Deleting an `incidents` row cascades through its videos (and their `video_analyses` and crops), its revisions (and the `evidence_crops` and `query_results` that name them) and its match suggestions. Deleting a `videos` row removes its analyses and crops but leaves the incident's revisions. `model_runs` is linked to revisions and analyses by a required foreign key, so a run row comes first. The append-only trigger permits only the incident cascade, so delete a video or an incident rather than a revision.
- **Changing a function signature:** drop the old signature in the same migration. PostgREST rejects ambiguous overloads that share parameter names.
- **Never** print or commit the service-role key, public key or DSN. Backend code uses the service role server-side only.

## Instructions

### Run the SQL harness (no Supabase, no network)

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/supabase/tests
uv run --no-project --python 3.12 --with pgserver --with 'psycopg[binary]' python test_baseline.py   # every migration, then every other test_*.py (incl. the mvp3 ones)
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
curl -s "$INCIDENT_SUPABASE_URL/rest/v1/report_revisions?incident_id=eq.<id>&select=*&order=revision_no.desc" \
  -H "apikey: $INCIDENT_SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $INCIDENT_SUPABASE_SERVICE_ROLE_KEY"
```

With an `sb_secret_...` key (finals) send `apikey` only: drop the `Authorization` line.

### Finals keys (`sb_secret_`)

Finals has no legacy JWT keys: the server key is `sb_secret_...` and the public key `sb_publishable_...`. They are not JWTs, so the Supabase gateway rejects one sent as `Authorization: Bearer` ("invalid JWT"); send it in the `apikey` header only. Who sends the key, and whether it copes:

| Sender | How | Handles `sb_secret_`? |
|---|---|---|
| `vss-agent` (`utils/incident_db.py`, and through it `SupabaseSearchStore`) | `supabase-py` `acreate_client` | Depends on the installed `supabase` version: `pyproject.toml` only requires `supabase~=2.0` and `uv.lock` does not pin it. Older 2.x releases validate the key as a JWT and raise `Invalid API key` (2.15.x still does; 2.18.0 and later do not). Prove it with the VM key check (step 4) |
| `mock-backend/base_profile_mock` (mock mode) | Same `incident_db`, its own venv | Yes: its `uv.lock` pins `supabase` 2.31.0 |
| `incident-console-v2` `src/lib/postgrest/client.ts` | `apikey`; Bearer only for JWT-style (`eyJ...`) keys | Yes |
| `eval/db_postgrest.py` | `apikey`; Bearer only for JWT-style (`eyJ...`) keys | Yes |
| Archived `archived/incident-console/db_postgrest.py` | `apikey` + always `Authorization: Bearer` | No (archived; never point it at finals) |
| `supabase/tests/probe_api.sh` | `apikey`; Bearer only for `eyJ...` keys | Yes |
| `supabase/copy/`, `parity_check.py`, `supabase` CLI | Direct DSN, no key | Not affected |

Follow-ups (not in this change): pin a minimum `supabase` version in `services/agent/pyproject.toml` and lock it in `uv.lock`.

### R2 objects

- **One bucket for both phases:** finals and the midterm record name the same keys; nothing was copied. A delete in finals also removes the object the midterm record names.
- **Keys:** all new user uploads go to `uploads/<original file name>` in both modes (a taken name gets `-2`, `-3`; unsafe characters become `_`; max 150 characters; never overwritten). Classified seed/evaluation clips remain under `anomaly/<category>/<file>`.
- **Valid keys** (per `isValidR2Key`): not absolute, no `.`/`..` prefix. VST `./streamer/media/...` paths are not keys.
- **Durability check:** `verifyR2Video` uses `HeadObject`; direct uploads require an exact nonzero byte-length match, and analysis requires a nonempty object before inference.
- **Playback** is by 1-hour presigned GET only. The bucket is private.
- **Report-card thumbnails:** new uploads use `thumbnails/<video-key>.webp`, derived by `thumbnailKeyForVideo`; legacy videos may have no thumbnail and use the UI skeleton. Deleting a video deletes this derived object too.
- **Evidence images** live under `evidence/<video key>/run-<N>/` (AI crops, and `<itemId>-frame.jpg` beside each: the whole frame) and `evidence/<video key>/edit-<N>/` (reviewer images); `<video key>` is `videos.filepath`. A revision's `evidence` (and `evidence_crops.image`) names the keys it shows, and older revisions keep naming images a reviewer later replaced, so an image is only an orphan when no revision or crop row of that video names it. `merge_incidents` and `remove_video` return the keys that went with deleted rows. `POST /api/reports/<videoId>/evidence-sweep` (dry run by default) lists such orphans older than `minAgeHours` (default 24); `{"dryRun": false}` removes them. Deleting a video (`DELETE /api/reports/<videoId>/delete`) removes its video, thumbnail and every `evidence/<video key>/` object before the rows, and keeps the rows if any removal fails. Images of videos deleted before 2026-10-25 are still in R2, and the sweep cannot reach them (it needs the video row).

### Renaming old R2 objects (finals only, done)

Objects written before 2026-10-28 on **finals** had hashed names; `supabase/r2/migrate_r2_names.py` renamed them (live run done, old copies deleted). It relied on the SQL function `apply_r2_rename` from `20261028090000_r2_rename.sql`. **mvp3 drops `apply_r2_rename`** (`20261030100000_revisions_per_incident.sql`): the mvp3 database starts with real names, so there is nothing to rename and the script cannot be used against it. Do not re-create the function there.

## After changing anything

In the same PR:
- Add or extend a `supabase/tests/test_*.py` for the new behaviour (`test_baseline.py` applies every migration and runs them all).
- Update the table specs in [`.docs/data.md`](../../.docs/data.md).
- Update [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md) if report fields moved.
- Update [`.docs/status.md`](../../.docs/status.md) if the migration was applied live.
- Add a [`.docs/decisions.md`](../../.docs/decisions.md) entry for any schema decision.
