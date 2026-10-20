---
name: incident-manage-database
description: Use to inspect or change the incident Supabase Postgres schema, write and apply a migration under supabase/migrations/, query incident/review/ground-truth tables, or locate and validate video objects in Cloudflare R2. Not for running an analysis (use incident-analyze-video) or scoring ground truth (use incident-run-eval).
license: Apache-2.0
metadata:
  version: "0.1.0"
  profile: "dev-profile-incident"
  tags: "incident supabase postgres migration postgrest r2"
---
# Incident Manage Database

Supabase is the **shared, live** team database. There is no staging copy, so treat every write as production.

Canonical facts: [`.docs/data.md`](../../.docs/data.md) (ERD, table specs, `insert_incident` RPC, cascades, R2 layout). Migration mechanics: [`supabase/README.md`](../../supabase/README.md).

## Access routing

| Caller / network | Client | Credentials |
|---|---|---|
| Agent on `kwanz-ws` (port 5432 DPI-blocked) | PostgREST over HTTPS (`supabase-py`) | `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` |
| `incident-console-v2` and `eval/` writers | PostgREST (console: adapters in `lib/adapters/supabase/` plus the not-yet-migrated callers listed in §7 of [`.docs/mvp2/console-hexagonal-architecture.md`](../../.docs/mvp2/console-hexagonal-architecture.md), all over `lib/postgrest/client.ts`; `eval/db_postgrest.py`) | same |
| Laptop tooling, `supabase` CLI, v1 console | Direct Postgres | `INCIDENT_DB_DSN` (session pooler, 5432). Strip any `+psycopg2` suffix for the CLI. |

All PostgREST writers must use `/rpc/insert_incident` for the `incidents` + `review_status` pair. PostgREST has no client-held transactions.
The report library reads filtered, paginated metadata through the service-role-only `/rpc/list_incident_report_summaries`; its `p_entities`, `p_instruments`, and `p_assets` arrays filter the normalized evidence tables by `(incident_id, model_run_id)`. It also takes `p_scope` (`all`/`official`), `p_entity_types`, `p_evidence_match` (`contains`/`exact`), and `p_timezone` (default `'UTC'`) for localised weekday and time-of-day filtering, and returns each report's analysis `outcome` and `isOfficial`. Reviewer edits use `/rpc/apply_structured_report_edit`, which atomically replaces one run's structured projection and sets `review_status.edited_by/edited_at`; it never modifies `model_runs.notes` (the immutable analysis record). Official reports are set only through `/rpc/select_official_report` / `/rpc/clear_official_report`. The library path does not read or sign video.
The operations dashboard reads bounded aggregates through the service-role-only `/rpc/get_incident_dashboard`, counting official incidents only and accepting `p_timezone` (default `'UTC'`) for local-time heatmap bucketing; it never downloads full report notes or evidence rows.
Natural-language search queries evidence items through the service-role-only `/rpc/search_evidence_items`, which performs a pgvector cosine distance search over `evidence_crops.embedding` strictly scoped to official reports (`videos.selected_model_run_id = ec.model_run_id`); search hits and critic verification verdicts are logged into `query_results`.
`evidence_crops` is loaded by `scripts/backfill_official_timestamps.py` (remote VLM grounding and boxes, R2 upload, remote embeddings); rows are upserted, so rerunning is safe. The search route embeds queries with the same model, so a model change means re-embedding every row.
`model_runs` rows without an incident are normal: failed analysis attempts (`contract_failed` / `request_failed`) and runs whose report was deleted. Never count `model_runs` rows as analyses without filtering by `run_outcome(notes)`. PostgREST embeds between `videos` and `incidents` must name `incidents_incident_id_fkey` (two relationships since `20260927170000`).

## Rules

- **Migrations are the schema authority** for new changes. Add a timestamped file `supabase/migrations/YYYYMMDDHHMMSS_<what>.sql`. Never hand-edit the live DB without a matching migration file.
- **Dry-run first, then ask** before applying for real. Applying is live and shared.
- **Cascades are real.** Deleting a `videos` or `model_runs` row, or re-running `insert_incident` under the same `model_run_id`, cascades through the evidence, review, notification and match tables. Callers must re-insert evidence after the RPC.
- **Changing a function signature:** drop the old signature in the same migration. PostgREST rejects ambiguous overloads that share parameter names.
- **New functions:** add `REVOKE ALL ON FUNCTION ... FROM PUBLIC, anon, authenticated` and `GRANT EXECUTE ... TO service_role` in the same migration. Default privileges only cover objects created by `postgres`.
- **Never** print or commit the service-role key or DSN. Backend code uses the service role server-side only. RLS lockdown (migration `20261016000000_enable_rls_and_lockdown_anon.sql` for existing tables, and `20261016120000_mvp2_evidence_search_and_crops.sql` for MVP2 tables: default-deny for anon and authenticated roles) is pending until migrations are applied; until then anon still has full access. Service-role and direct postgres bypass RLS (see [`.docs/data.md`](../../.docs/data.md) and [`.docs/status.md`](../../.docs/status.md#4-known-issues)).

## Instructions

### Apply a migration

From the repo root:

```bash
# 1. Always inspect local vs remote migration state first
supabase migration list --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN"

# 2. Preview what would be applied — review output, then ask captain/lead
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN" --dry-run

# 3. Apply for real
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN"
```

If an older-timestamped migration is pending after a newer one has already been applied remotely (e.g. `20261016120000` applied while `20260928000000` is pending), `supabase db push` will refuse to apply it out-of-order. Use `--include-all` to force applying older pending migrations:

```bash
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN" --include-all --dry-run
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN" --include-all
```

If a migration was applied manually or out-of-band and needs to be marked as applied (or unapplied) in Supabase's migration tracking table without re-executing SQL, use `supabase migration repair`:

```bash
supabase migration repair --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN" --status applied <YYYYMMDDHHMMSS>
```

### Read via PostgREST (works from anywhere with HTTPS)

```bash
curl -s "$INCIDENT_SUPABASE_URL/rest/v1/incidents?incident_id=eq.<id>&select=*" \
  -H "apikey: $INCIDENT_SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $INCIDENT_SUPABASE_SERVICE_ROLE_KEY"
```

### R2 objects

- **Keys:** all new user uploads go to `uploads/<encodeURIComponent(sensorId)>/<uuid><ext>` in both modes. Classified seed/evaluation clips remain under `anomaly/<category>/<file>`.
- **Valid keys** (per `isValidR2Key`): not absolute, no `.`/`..` prefix. VST `./streamer/media/...` paths are not keys.
- **Durability check:** `verifyR2Video` uses `HeadObject`; direct uploads require an exact nonzero byte-length match, and analysis requires a nonempty object before inference.
- **Playback** is by 1-hour presigned GET only. The bucket is private.
- **Report-card thumbnails:** new uploads use `thumbnails/<video-key>.webp`, derived by `thumbnailKeyForVideo`; legacy videos may have no thumbnail and use the UI skeleton. Deleting a video deletes this derived object too.

## After changing anything

In the same PR:
- Update the ERD and table specs in [`.docs/data.md`](../../.docs/data.md).
- Update [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md) if report fields moved.
- Update [`.docs/status.md`](../../.docs/status.md) if the migration was applied live.
- Add a [`.docs/decisions.md`](../../.docs/decisions.md) entry for any schema decision.
