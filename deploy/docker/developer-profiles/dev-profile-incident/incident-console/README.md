<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# incident-console

Streamlit console for the VSS incident search & reporting capstone. Front-end
migrated from the sibling `rise-up` project onto this blueprint fork. See
[`incident-plan/`](../incident-plan/) for the full plan;
this app implements the frontend half of
`incident-plan-implementation-shared.md` §3 and §5.

This package is **profile-exclusive** — it lives here, not under the shared
`deploy/docker/services/` tree.

## Local dev loop (no Docker, no GPU)

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
uv sync
uv run streamlit run app.py
```

The app imports and starts with nothing else running, but it is **database-backed
and has no offline mode**: `INCIDENT_DB_DSN` must be set for any page to show
data (see the next section). Other dependencies still degrade gracefully:

- **No `INCIDENT_DB_DSN`** → every page shows a visible *database not configured*
  state instead of erroring; no incident data is rendered.
- **No agent** → the AI-trigger calls fail soft with a notice.
- **No `INCIDENT_VIDEO_BASE_URL` and no R2 keys** → playback shows the stored key
  and the incident window instead of a player.

## Supabase Postgres + the 8-mock seed

With `INCIDENT_DB_DSN` set, the pages read and write incidents through `db.py`
(`IncidentDB`), so field edits, review-status changes, video re-links and
severity ratings persist across a refresh. `init_schema()` creates every table
on first use (`checkfirst=True`; no additive column backfill — the schema is
created fresh, not migrated).

**Secrets never go in a tracked file.** `dev-profile-incident/.env` is committed
and stays placeholders. For local dev, put the real Supabase DSN and
Cloudflare R2 keys in `incident-console/.env.local` (untracked, loaded by
`config.py` with `override=True`), which `incident-console/.gitignore` keeps out of
git. For the VM deploy, edit the real values into the ignored `generated.env.local` /
`generated.env.remote` copy instead (see the local/remote implementation docs,
§2) - never into `.env.local` on the build host.

A tracked, copyable template listing every required key exists at
`incident-console/.env` — copy it to `.env.local` and fill in real
values:

```bash
cp .env .env.local
```

```dotenv
# incident-console/.env.local  (untracked)
INCIDENT_DB_DSN=postgresql+psycopg2://USER:PASSWORD@HOST:5432/postgres?sslmode=require
R2_ACCOUNT_ID=...
R2_ACCESS_KEY=...
R2_SECRET_KEY=...
R2_BUCKET=anomaly-detection-dataset
INCIDENT_SUPABASE_URL=https://<project-ref>.supabase.co
INCIDENT_SUPABASE_SERVICE_ROLE_KEY=...
```

Use the Supabase **session pooler** (port 5432), or the direct connection if your
network has IPv6 - not the transaction pooler (port 6543); "Database connection"
below has the reasons and the documentation behind them. Percent-encode reserved
characters in the password (`@` → `%40`).

Load the 36 real (video-backed) CSV-fixture incidents once (idempotent, manual,
never runs on startup):

```bash
uv run python scripts/seed_supabase.py
```

It upserts one `videos` row per incident (natural key: the incident id itself
- 1 video = 1 incident), one shared `model_runs` row (`MR-SEED`), and each
incident's `incidents` / `entities` / `instruments` / `assets` rows. Re-running
updates in place — row counts do not grow. The dataset lives in
`fixtures/data/*.csv`, parsed via `scripts/seed_data.py`. Each video's
`filepath` is the real `anomaly/<category>/<filename>` object key in the
`anomaly-detection-dataset` R2 bucket (verified live; see `scripts/seed_data.py`
for the category → folder mapping). 36 of the 72 rows on disk are
`SYN-`-prefixed synthetic placeholder rows with no corresponding real R2
object; `scripts/seed_data.py` drops them before seeding, so only the 36 real,
video-backed incidents are ever loaded.

Separately, load the captain's own 8-video custom demo set (idempotent,
manual, never runs on startup, independent of the seed above):

```bash
uv run python scripts/seed_mock8.py
```

It upserts 8 `videos` rows pointing at the captain's `normal_videos/*.mp4` R2
uploads plus their own `incidents` / `entities` / `instruments` / `assets`
rows, all under a dedicated `model_runs` row (`MOCK8`) so this set can never
collide with or be overwritten by the `MR-SEED` reseed above. See
`scripts/seed_mock8.py` for the incident content and its clip.

### Database connection: mode, speed and dropped connections

The console reaches Postgres through the DSN (`INCIDENT_DB_DSN`, SQLAlchemy + psycopg2); there is no REST
layer in between, so "use the DSN" is already how it works. Page speed is decided by two things: how many
**network round trips** each query costs (every one pays the full RTT to the pooler) and which endpoint the
DSN points at. [`db_connection.py`](db_connection.py) is the authoritative description of what the code does;
this section has the measurements and the documentation behind the choices.

**Round trips, before → after.** Measured by `scripts/measure_db_roundtrips.py` on real PostgreSQL 16.2 behind a
proxy that counts wire round trips and injects latency. It is a model of the network (no TLS, no pooler, no real
Supabase project): the round-trip *counts* are protocol-level and carry over, the milliseconds are the injected
RTT times those counts, and the "dropped connection" rows leave out the failed first attempt (the proxy closes
instantly; on a real link add about one RTT to notice it).

| scenario (real PostgreSQL 16.2, local; latency injected) | wire round trips | ms at 30 ms RTT | ms at 80 ms RTT |
|---|---|---|---|
| page run: get_db_or_notice() [health cache cold] | 4 → 1 | 123 → 31 | 323 → 81 |
| page run: get_db_or_notice() [health cache warm] | 4 → 0 | 123 → 0 | 323 → 0 |
| query: get_video (1 PK lookup) | 4 → 1 | 124 → 32 | 324 → 82 |
| query: list_latest_incidents (join, 36 rows) | 4 → 1 | 127 → 34 | 327 → 84 |
| query: list_notifications | 4 → 1 | 125 → 32 | 324 → 82 |
| page-like: 1 page run + 10 x get_video | 44 → 10 | 1,360 → 316 | 3,564 → 816 |
| write: update_video (1 UPDATE) [transactional pool warm] | 4 → 3 | 125 → 96 | 334 → 245 |
| write: the process's first write [transactional pool cold] | 4 → 13 | 126 → 414 | 326 → 1,058 |
| dropped pooled connection: page run + get_video | 8 → 3 | 250 → 97 | 652 → 248 |
| dropped pooled connection: write (update_video) | 4 → 4 | 129 → 131 | 330 → 330 |
| cold start: fresh process, 1 page run + 1 query | 38 → 11 | 1,188 → 352 | 3,088 → 898 |

- **Reads: 4 → 1.** Every query used to pay `pool_pre_ping`'s `SELECT 1`, psycopg2's implicit `BEGIN`, the
  statement and the pool's `ROLLBACK`; only one in four carried data. Reads now run on `IncidentDB.read_engine`,
  a separate engine whose connections are AUTOCOMMIT (psycopg2 sends no `BEGIN`; the pool's `ROLLBACK` is a
  no-op), and nothing is sent to validate a pooled connection.
- **Never a global AUTOCOMMIT.** AUTOCOMMIT is not atomic, so it exists only on that read engine, which refuses
  write statements (`WriteOnReadEngine`). Writes use `IncidentDB.engine`, the ordinary transactional engine
  (`engine.begin()`, native transactions). The read engine needs its *own* pool: switching AUTOCOMMIT on per
  checkout (`execution_options`), or on a shared pool, costs **2** round trips per read, not 1, because SQLAlchemy
  resets the isolation level on every return to the pool and psycopg2 then sends
  `SET default_transaction_isolation TO DEFAULT` (seen on the wire, steady state over repeated reads).
- **The price.** The transactional engine is a second engine, set up on its first connection, so a process's
  *first write* costs about 10 more round trips (13 above), once; every later write costs 3 instead of 4. Both
  pools are small (read 2 + 3 overflow, write 1 + 2) because in Supavisor's session mode each client connection
  holds a pooler slot.
- **Health probe.** `ui.get_db_or_notice()` no longer queries on every rerun. Any statement the database answered
  within `INCIDENT_DB_HEALTHCHECK_TTL_SECONDS` (default 15; `0` probes every run) counts as proof, so a page run
  right after start-up or another page run sends nothing; otherwise the probe is one round trip. A connection
  error cancels the shortcut at once, so at most one page run inside the window can hit the outage itself; the
  next shows the "unreachable" notice.
- **Start-up.** The schema check is one catalog query instead of one per table (38 → 11 round trips for a fresh
  process's first page).
- **Dropped connections.** A pooled connection killed by the pooler or the network used to be caught by the
  pre-ping. Now the first call to find it dead is **replayed once** on a fresh connection, transparently, whether
  it reads, writes or does both. It is never replayed once a COMMIT was attempted (the outcome is unknown), and an
  error that is not a lost connection is never replayed. This is SQLAlchemy's documented pattern: "The canonical
  approach to dealing with mid-operation disconnects is to retry the entire operation from the start of the
  transaction", and it calls AUTOCOMMIT reads the case for "a limited form of transparent reconnect"
  ([FAQ](https://docs.sqlalchemy.org/en/20/faq/connections.html#how-do-i-retry-a-statement-execution-automatically)).
- **Observing it.** The two engines are separate pools with separate event streams: anything that counts
  statements or checkouts must listen on both (`for engine in handle.engines: event.listen(engine, ...)`), and a
  new read belongs on `self.read_engine.connect()` (one round trip), not `self.engine.connect()` (three).

**Which DSN.** Verbatim quotes from the official documentation:

| endpoint | what the documentation says | here |
|---|---|---|
| Direct, `db.<ref>.supabase.co:5432` | "Use it for persistent backends, such as virtual machines (VMs) and long-running containers." It is IPv6-only unless the project has the IPv4 add-on ([connecting](https://supabase.com/docs/guides/database/connecting-to-postgres)). On the SQLAlchemy page: "For stationary servers, such as VMs and long-running containers, it is recommended to use your direct connection string" ([using SQLAlchemy](https://supabase.com/docs/guides/troubleshooting/using-sqlalchemy-with-supabase-FUqebT)) | The documented first choice for a long-lived process, if your host has IPv6 (`curl -6 https://ifconfig.co/ip`). Compare it with `scripts/db_timing.py`. |
| Session pooler, `aws-N-<region>.pooler.supabase.com:5432` | "Use it as an alternative to a direct connection when you connect from an IPv4-only network." (connecting page) | **The current DSN; keep it** unless direct works from your network. |
| Transaction pooler, `...:6543` | "Use it for serverless and edge functions, which open many short-lived connections." "Transaction mode does not support prepared statements." "Session-level state is lost between transactions. This covers set and reset, session-level advisory locks, listen and notify, and temporary tables." (connecting page). "When using transaction mode, you should use the NullPool setting" (SQLAlchemy page) | Do not use it: it is meant for serverless, and this app keeps a pool (psycopg2 sends the merged query text, so prepared statements would not bite, but NullPool would mean a new TLS handshake and login for every query). |
| Cloudflare Hyperdrive | "It will provide a secure connection string that is only accessible from your Worker" ([Hyperdrive get started](https://developers.cloudflare.com/hyperdrive/get-started/)); its local-development mode bypasses the pooling ([docs](https://developers.cloudflare.com/hyperdrive/configuration/local-development/)) | **Not applicable** to a Streamlit process. Text saying the database is "via Cloudflare Hyperdrive" (`.env` header comments, plan docs, older versions of `db.py` and `compose.yml`) is stale. |

Two older claims are not supported by the documentation: that Hyperdrive pools this app's connections (above),
and that 5432 is needed "so DDL and `SELECT ... FOR UPDATE` work". Neither Supabase's nor PgBouncer's documentation
says DDL or `FOR UPDATE` fail in transaction mode; what they document is the loss of session state (`SET`, session
advisory locks, `LISTEN`/`NOTIFY`, temporary tables) and of prepared statements. For a persistent backend
Supabase says "an application-side pooler is enough on its own"
([pooling and limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits)),
which is what SQLAlchemy's pool is here. No pooler-versus-direct latency figure is published, and the region
matters more than the mode ("Choose the location closest to your users for the best performance",
[regions](https://supabase.com/docs/guides/platform/regions)): measure your own before deciding.

**Connection settings.** Defaults live in `db_connection.py`; any libpq one can be overridden in the DSN
(`?keepalives_idle=60`). They are judgment calls informed by the documentation, not vendor-prescribed values:

| setting | default | why |
|---|---|---|
| `connect_timeout` | 10 s | libpq: "Zero, negative, or not specified means wait indefinitely" ([libpq](https://www.postgresql.org/docs/current/libpq-connect.html)). A black-holed host would freeze the page instead of showing the "unreachable" notice. |
| `keepalives_idle` / `_interval` / `_count` | 30 s / 10 s / 3 | Linux's default idle time is 7200 s ([tcp(7)](https://man7.org/linux/man-pages/man7/tcp.7.html)); Supabase notes "the connection pooler or NAT may drop inactive connections" ([troubleshooting](https://supabase.com/docs/guides/troubleshooting/troubleshooting-connect_timeout-or-hanging-queries-in-vercel-serverless-functions-775f92)). A dead peer is noticed after 30 + 3 x 10 s of silence. |
| `tcp_user_timeout` | 30 s | Keepalives only run on an idle socket; this bounds data that is sent but never acknowledged. Otherwise TCP retransmits 15 times, "approximately between 13 to 30 minutes" (tcp(7)). Needs libpq 12+; the psycopg2 wheel bundles libpq 17. |
| `pool_recycle`, `INCIDENT_DB_POOL_RECYCLE_SECONDS` | 600 s | Supavisor has a `client_idle_timeout` setting ("the maximum duration of an idle client connection", [tenants](https://github.com/supabase/supavisor/blob/main/docs/configuration/tenants.md)) but the hosted value is **not documented**, so keep connections young. `scripts/db_timing.py --idle 60,300,600` measures whether an idle connection survives on your project. |
| `INCIDENT_DB_HEALTHCHECK_TTL_SECONDS` | 15 | See "Health probe". |

**TLS.** `sslmode=require` is Supabase's floor, but it "encrypts the connection but doesn't verify the server, so
it doesn't stop a man-in-the-middle attack"; Supabase and libpq both recommend `verify-full` with the CA
certificate from the dashboard (`sslrootcert=...`). A *new* connection also pays for TLS and login. libpq's
documentation does not count those round trips; Cloudflare counts "the TCP handshake (1x), TLS negotiation (3x),
and database authentication (3x)" for its own path (a vendor figure, not measured here), which is why the pools
keep connections alive rather than reconnecting. `sslnegotiation=direct` (libpq 17+, needs `sslmode=require` or
higher) "requires one fewer round trip", but whether Supavisor accepts it is not documented, so it is not enabled.
Without TLS or SCRAM the harness measures 1 round trip for a new connection, plus roughly 7-9 more, once per
engine, for SQLAlchemy's first-use setup.

**Measure on your own network.** `uv run python scripts/db_timing.py` compares the current settings with the
previous ones over your real DSN: read-only, prints no secrets (never the DSN, host, user, password, database name
or an IP address) and writes nothing; add `--idle 60,300` to test whether idle connections survive. To reproduce the
table above locally: `uv run --with pgserver python scripts/measure_db_roundtrips.py` (a disposable Postgres from
a wheel; no credentials).

### Mock LLM (exercise the AI-trigger path with zero GPU)

`mock_llm_server.py` is a tiny OpenAI-compatible stub. It is **local-dev only**
and is never deployed to the VM.

```bash
uv run uvicorn mock_llm_server:app --port 8900
# then, in the console's environment:
export INCIDENT_LLM_BASE_URL=http://localhost:8900/v1
```

`POST /v1/chat/completions` returns a canned completion whose `content` is an
`IncidentReport`-shaped JSON blob (`incident_type`, `severity` 1–5,
`confidence`, `incident_start`/`incident_end`, `description`, `persons[]`). It
exercises the same route → parse → Postgres-write path the real agent will use
for the deferred report-generation flow (`agent_client.py`). The same route
also branches on a judge-shaped request (`model="incident-judge"`, or the
`INCIDENT_JUDGE_REQUEST` marker in the system prompt) and returns a
deterministic text-similarity score instead — see "Tier 1 GT evaluation"
below.

`POST /v1/embeddings` returns a deterministic hashed bag-of-words vector (64
dims) per input text — real cosine separation (reworded-but-similar text
scores high, unrelated text scores low) with no ML dependency beyond what
`matching.py` already imports. Set `INCIDENT_EMBEDDING_BASE_URL` to the same
`http://localhost:8900/v1` to exercise `matching.py` locally.

The local `base_profile_mock` implements
`POST /api/v1/incidents/{id}/analyze` as an explicitly mock, Postgres-backed
report generator. The real `vss-agent` analyze route now exists
(`services/agent/src/vss_agents/api/incident_analyze.py`, merged in PR #38)
but isn't reachable on the deployed VM yet — see `DEPLOY_NOTES.md`'s Known
Issue #1 (no `build:` wiring for vss-agent's container). `POST /api/v1/search`
is still unbuilt (MVP2), so the client keeps returning a "not implemented yet"
notice for that one.

### Tier 1 GT evaluation (mock backend, no live VSS)

`eval_gt.py` scores one model run's `incidents`/`entities`/`instruments`/
`assets` against the parallel `gt_*` ground-truth tables: normalized exact
match for `type`, exact match for `severity_level`, an LLM-as-a-judge
0.0–1.0 semantic score for `description` (via `INCIDENT_LLM_BASE_URL`, the
same mock/real chat-completions endpoint above), and tolerance comparisons
(`config.EVAL_TIMESTAMP_TOLERANCE_SECONDS`) for the timestamps/duration. It
reuses `matching.py` unchanged for entities/instruments/assets and derives
TP/FP/FN/Precision/Recall/F1 from the accepted matches. `run_evaluation(db,
incident_id, model_run_id)` is the one orchestration entry point; the
"Ground-truth evaluation" section on the report-detail page
(`report_detail.py`) calls it via `DBReports.run_gt_evaluation()` and renders
the result — it appears only for incidents that already have a `gt_incidents`
row.

Seed a 5-incident demo set (real CSV-fixture ground truth + a deterministically
perturbed model run under its own `MR-EVAL-DEMO` model run, covering a
reworded-but-equivalent description, an in-tolerance and an out-of-tolerance
timestamp, a semantically-similar entity match, an extra model entity (false
positive), and a missing model asset (false negative) — one-time, manual,
never on startup, same contract as `seed_mock8.py`):

```bash
uv run python scripts/seed_gt_demo.py
```

### Real backend on kwanz-ws via SSH tunnel (Phase 4)

The console runs on your laptop; the real backend (vss-agent, LLM/VLM NIMs)
runs on kwanz-ws. An SSH tunnel connects the two — same pattern as the
base-profile VSS UI tunnel. The mock LLM above stays laptop-only for the
zero-GPU loop; use this path when you want the real backend instead. (Or run
`../start.sh` to automate this — see that profile's README.)

Terminal 1 (tunnel):
 
```bash
# laptop side; forwards localhost:8000/:30081/:30082 to the VM
../scripts/tunnel.sh  # replaces the old mdx-tunnel-incident alias (from ../README.md's script table)
```

Terminal 2 (console, same directory as the local loop):

```bash
# incident-console/.env.local  (untracked; real values live only here)
INCIDENT_AGENT_BASE_URL=http://localhost:8000
INCIDENT_LLM_BASE_URL=http://localhost:30081/v1
```

```bash
uv run streamlit run app.py  # http://localhost:8501, talking to the VM backend
```

`INCIDENT_AGENT_BASE_URL` needs no change from the committed placeholder —
the tunnel forwards the backend's real port 8000 onto the same laptop port.
`INCIDENT_LLM_BASE_URL` switches from the mock (`:8900/v1`) to the tunneled
LLM NIM (`:30081/v1`). DB/R2 values stay as documented above (Supabase DSN +
R2 keys in `.env.local`); the tunnel carries only the agent/LLM/VLM traffic.

Prove the tunnel before starting the console:
 
```bash
../scripts/tunnel-check.sh  # replaces the old mdx-tunnel-incident-check alias
# agent ok (localhost:8000 -> 10.131.1.5:8000)
# nim :30081 -> 10.131.1.5:30081: HTTP 200
# nim :30082 -> 10.131.1.5:30082: HTTP 200
```

(The NIM lines only need to answer at HTTP level — any status code proves
the forward works.) Never deploy this console to the VM: the VM runs only
the backend stack.

### Tests

```bash
uv run pytest
```

Fast and hermetic — SQLite fixture for the data layer, `httpx.MockTransport`
for the agent client. No live Postgres / agent / GPU.

### Lint

```bash
uv run ruff check .
uv run ruff format --check .
```

## Environment variables

All are read by `config.py`, which loads the committed `../.env` placeholders
explicitly (not via `find_dotenv()`), then `./.env.local` (untracked
real secrets) with override. The old `incident-console/.env` is no longer
code-live. Real values and their source are documented below. On the VM deploy
nothing reads `.env` files inside the container - the real values live in the
ignored `generated.env.local` / `generated.env.remote` copy passed to
`docker compose --env-file`, interpolated into the container via `compose.yml`
`environment:` (see §2 of the local/remote implementation docs).

| Variable | Purpose | Real source |
|---|---|---|
| `INCIDENT_DB_DSN` | SQLAlchemy sync URL for the incident Postgres | Supabase Postgres (session pooler, port 5432); put it in `.env.local`. `incident-plan-implementation-shared.md` §1. A SQLite DSN also works for local iteration — production stays Supabase Postgres via the session pooler |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY` / `R2_SECRET_KEY` / `R2_BUCKET` | Cloudflare R2 for video clips + evidence screenshots (`r2_videos.py`) | The R2 bucket the captain uploaded footage to; put keys in `.env.local` |
| `INCIDENT_SUPABASE_URL` | Supabase project URL (`https://<project_ref>.supabase.co`) | Supabase Project Settings -> API. Used by `vss_agents.utils.incident_db` when running the local mock backend (`local-start.sh`) or direct agent tests |
| `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | Supabase `service_role` secret JWT | Supabase Project Settings -> API. Server-side only; put key in `.env.local` |
| `INCIDENT_AGENT_BASE_URL` | Base URL of vss-agent's upload + AI-trigger API | The running `vss-agent` service (`VSS_AGENT_PORT`, default `8000`); via the Phase 4 SSH tunnel this stays `http://localhost:8000` (see "Real backend on kwanz-ws via SSH tunnel" above) |
| `INCIDENT_LLM_BASE_URL` | OpenAI-compatible chat-completions base URL | `mock_llm_server.py` locally (`http://localhost:8900/v1`); the tunneled real NIM (`http://localhost:30081/v1`) under the Phase 4 tunnel above; vss-agent's `LLM_BASE_URL` / a real NIM on the VM |
| `INCIDENT_EMBEDDING_BASE_URL` | OpenAI-compatible embeddings base URL for `matching.py` | `mock_llm_server.py`'s `/v1/embeddings` locally (`http://localhost:8900/v1`); the platform's real embedding endpoint otherwise; unset means matching fails soft to no matches |
| `INCIDENT_VIDEO_BASE_URL` | Optional playback URL prefix; unset uses R2 presigned URLs | The R2 bucket public/presigned URL prefix |
| `INCIDENT_SEVERITY_NOTIFY_THRESHOLD` | Severity ≥ this raises a notification on verify (default `4`) | **Plan default, not spec** — confirm with the team |
| `INCIDENT_HTTP_TIMEOUT_SECONDS` | HTTP client timeout in seconds (code default `15.0`) | Set only if the default is wrong; VM value goes in the `generated.env.*` copy |
| `INCIDENT_CONSOLE_PORT` | Host port for the Streamlit server in the VM deploy (default `8501`) | Set in the `generated.env.*` copy only if non-default |
| `INCIDENT_DB_HEALTHCHECK_TTL_SECONDS` | Seconds a good database answer lets a page run skip its health probe (default `15`; `0` probes every run) | Set only if the default is wrong; see "Database connection" |
| `INCIDENT_DB_POOL_RECYCLE_SECONDS` | Max age of a pooled connection before it is replaced (default `600`; `-1` never) | Tune from `scripts/db_timing.py --idle ...`; see "Database connection" |

## VM deploy

`Dockerfile` + `compose.yml` here are for the VM deploy only (service
`incident-console`, compose profile `bp_developer_search_2d`). Local dev never
uses them. The image is a `uv sync --frozen --no-dev` multi-stage build per
`incident-plan-implementation-shared.md` §3. Never create `.env` / `.env.local`
with real values on the VM build host: `COPY . .` would bake them into the image
(see `.dockerignore`).

## Layout

| File | Role |
|---|---|
| `app.py` | Entry point / navigation home + environment panel |
| `pages/2_Report_Review.py` | Report review + edit + review status + jump-to-timestamp (database-backed) |
| `pages/3_Dashboard.py` | Filters + aggregate insights over DB incidents + linked evidence (database-backed) |
| `db.py` | Direct-Postgres data layer (sync SQLAlchemy Core): `videos` / `queries` / `model_runs`, model-output `incidents` / `entities` / `instruments` / `assets` (keyed by `model_run_id`), ground-truth `gt_incidents` / `gt_entities` / `gt_instruments` / `gt_assets`, `entity_matches` / `instrument_matches` / `asset_matches`, `review_status`, `notifications`, `severity_eval_log` |
| `db_reports.py` | Postgres-backed Incident view model (edits persist; reads the most recent model run per incident) |
| `r2_videos.py` | Read-only R2 catalog, presigned playback / screenshot URLs, bucket picker helpers |
| `embed_client.py` | Embedding-endpoint HTTP client (fail-soft), used by `matching.py` |
| `matching.py` | Similarity-based matching of one model run's entities/instruments/assets against ground truth (Hungarian assignment + threshold) |
| `eval_gt.py` | Tier 1 GT evaluation: incident field scoring (type/severity/description-judge/timestamps/duration), TP/FP/FN/P/R/F1 from `matching.py`'s output, and the `run_evaluation()` orchestration entry point |
| `scripts/seed_data.py` / `scripts/seed_supabase.py` | The 36 real, video-backed CSV-fixture incidents (one shared `model_run_id`; the 36 synthetic `SYN-`-prefixed placeholder rows are dropped, having no matching R2 video) + evidence, and the one-time idempotent importer |
| `scripts/seed_mock8.py` | The captain's 8-video custom demo set (its own `model_run_id`, `MOCK8`) + evidence, independent one-time idempotent importer |
| `scripts/seed_gt_demo.py` | 5-incident Tier 1 GT-evaluation demo set: real CSV-fixture ground truth + a deterministically perturbed model run (`MR-EVAL-DEMO`), independent one-time idempotent importer |
| `agent_client.py` | vss-agent upload + AI-trigger HTTP client (fail-soft) |
| `catalog_actions.py` | Pure (no `streamlit`) upload/record helper used by the Incident Reports upload flow, incl. the `videos.id`-fitting `derive_video_id()` |
| `incident_report.py` | `IncidentReport` schema + `INCIDENT_TYPES` (road accident / burglary / explosion / fighting / animal) + pure helpers |
| `config.py` | Env-driven configuration (`.env` then untracked `.env.local`) |
| `theme.py` / `ui.py` | Shared look-and-feel and page helpers |
| `mock_llm_server.py` | Local-dev-only OpenAI-compatible stub |
