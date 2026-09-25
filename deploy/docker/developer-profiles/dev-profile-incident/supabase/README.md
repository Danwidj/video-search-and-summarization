# Supabase migrations — dev-profile-incident

This is a Supabase CLI project directory scoped to the incident-console's own
Postgres schema (`--workdir` target for the `supabase` CLI). It is not a
fully initialized Supabase CLI project — there is no `config.toml`, and the
team has never run `supabase init`/`supabase link` here. `supabase db push
--workdir <this dir> --db-url <url>` works against a bare `migrations/`
directory with no further setup (verified with the CLI's own `--dry-run`).

## What's in here

`migrations/20260917141225_insert_incident_function.sql` creates the
`insert_incident` Postgres RPC function. This is live code, not a one-off
script: `services/agent/src/vss_agents/utils/incident_db.py`'s
`insert_incident()` calls it at runtime via PostgREST's `/rpc/insert_incident`
to get atomic delete-then-insert semantics across `incidents` +
`review_status` — PostgREST has no client-held transactions, so this RPC is
the only way that operation is atomic. The PostgREST writers in
`incident-console/db_postgrest.py` and `eval/db_postgrest.py` call the same
RPC. Do not delete this file only because nothing in the repo runs
`supabase db push` automatically; it is the only reason `insert_incident()`
doesn't corrupt state on every call.

`migrations/20260925031000_schema_defaults_and_precision.sql` adds real
server-side column defaults (UTC timestamps, `review_status.status`,
`notifications.acknowledged`) and replaces `insert_incident` so
`p_confidence_score` is `DOUBLE PRECISION`. See `../.docs/data.md` for the
resulting schema.

## Applying these migrations to a Supabase project

From the repo root, using the same `INCIDENT_DB_DSN` you already have
configured for local console dev (session-pooler URL, port 5432 — see
`../incident-console/README.md`'s Supabase section):

```bash
# Preview first — prints what would change, touches nothing:
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN" --dry-run

# Apply for real:
supabase db push --workdir deploy/docker/developer-profiles/dev-profile-incident \
  --db-url "$INCIDENT_DB_DSN"
```

If `$INCIDENT_DB_DSN` carries a SQLAlchemy driver suffix (e.g.
`postgresql+psycopg2://`), strip it to plain `postgresql://` first — `--db-url`
expects a standard libpq connection string, not a SQLAlchemy one.

Run this once after cloning against a fresh Supabase project, and again any
time a migration file is added or changed.
