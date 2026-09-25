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
| `incident-console-v2` and `eval/` writers | PostgREST (`lib/postgrest/client.ts`, `eval/db_postgrest.py`) | same |
| Laptop tooling, `supabase` CLI, v1 console | Direct Postgres | `INCIDENT_DB_DSN` (session pooler, 5432). Strip any `+psycopg2` suffix for the CLI. |

All PostgREST writers must use `/rpc/insert_incident` for the `incidents` + `review_status` pair. PostgREST has no client-held transactions.

## Rules

- **Migrations are the schema authority** for new changes. Add a timestamped file `supabase/migrations/YYYYMMDDHHMMSS_<what>.sql`. Never hand-edit the live DB without a matching migration file.
- **Dry-run first, then ask** before applying for real. Applying is live and shared.
- **Cascades are real.** Deleting a `videos` or `model_runs` row, or re-running `insert_incident` under the same `model_run_id`, cascades through the evidence, review, notification and match tables. Callers must re-insert evidence after the RPC.
- **Changing a function signature:** drop the old signature in the same migration. PostgREST rejects ambiguous overloads that share parameter names.
- **Never** print or commit the service-role key or DSN. Backend code uses the service role server-side only. RLS is currently disabled (see known issue 6, "RLS Disabled on Public Tables", in [`.docs/status.md`](../../.docs/status.md#2-known-issues--technical-debt)).
- Planned schema change (Option B: `r2_key`/`stream_url` split, `incident_timeline`, dropping legacy tables) is described in [`.docs/restructure-plan.md`](../../.docs/restructure-plan.md). Check whether it has been approved before touching those areas.

## Instructions

### Apply a migration

From the repo root:

```bash
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN" --dry-run          # review output, then ask
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN"
```

### Read via PostgREST (works from anywhere with HTTPS)

```bash
curl -s "$INCIDENT_SUPABASE_URL/rest/v1/incidents?incident_id=eq.<id>&select=*" \
  -H "apikey: $INCIDENT_SUPABASE_SERVICE_ROLE_KEY" \
  -H "Authorization: Bearer $INCIDENT_SUPABASE_SERVICE_ROLE_KEY"
```

### R2 objects

- **Keys:** vm-mode uploads go to `uploads/<encodeURIComponent(sensorId)>/<uuid><ext>`. Mock uploads and dataset clips go to `anomaly/<category>/<file>`.
- **Valid keys** (per `isValidR2Key`): not absolute, no `.`/`..` prefix. VST `./streamer/media/...` paths are not keys.
- **Playback** is by 1-hour presigned GET only. The bucket is private.

## After changing anything

In the same PR:
- Update the ERD and table specs in [`.docs/data.md`](../../.docs/data.md).
- Update [`.docs/analysis-schema.md`](../../.docs/analysis-schema.md) if report fields moved.
- Update [`.docs/status.md`](../../.docs/status.md) if the migration was applied live.
- Add a [`.docs/decisions.md`](../../.docs/decisions.md) entry for any schema decision.
