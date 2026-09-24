# Agent Notes

## Project overview & architecture

This repo is a fork of [NVIDIA's VSS Blueprint](https://docs.nvidia.com/vss/latest/index.html) — GPU-accelerated video AI agents (search, summarization, visual Q&A, alert verification) built from vision-language models, RAG, and NVIDIA NIM microservices. See the root [`README.md`](README.md) for the upstream project's overview, agent workflows, and software components, and its "Repository Structure Overview" table for what lives under `services/`, `deploy/`, `tools/`, `libs/`, and `skills/`.

**Compose profile architecture:** [`deploy/docker/README.md`](deploy/docker/README.md) is authoritative. The root `deploy/docker/compose.yml` combines three includes — `services/compose.yml` (shared infra/VIOS/UI/RTVI/NIMs), `developer-profiles/compose.yml` (developer profiles: `base`, `lvs`, `alerts`, `search`, plus this fork's `incident` profile below), and `industry-profiles/compose.yml` (e.g. `warehouse-operations`). Day-to-day developer stacks are brought up via `deploy/docker/scripts/dev-profile.sh up --profile <base|lvs|alerts|search> --hardware-profile <...>`, not hand-edited Compose.

**Deployment topology — two paths, pick per task:**
- **Full GPU-backed stack** (NIM containers, real inference): VM-only, brought up via `dev-profile.sh` (stock profiles) or direct `docker compose` (this fork's `incident` profile — see below). Requires an `NGC_CLI_API_KEY` and a GPU-equipped host.
- **Zero-GPU local mock**: [`deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the whole `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) behind one FastAPI process, so frontend work (`services/ui/apps/nv-metropolis-bp-vss-ui`, `incident-console-v2`) can happen on a laptop with no GPU, no NIM containers, and no VM deployment.

For this fork's own capstone work (team, VM specifics, incident-profile deploy mechanics), see the next section and its `dev-profile-incident/README.md`.

## Incident Search & Reporting Capstone (Daniel's team)

A video-driven incident search and reporting system is being built on this VSS blueprint fork, sponsored by NVIDIA NVAITC. The profile README and technical reference docs live under [`deploy/docker/developer-profiles/dev-profile-incident/`](deploy/docker/developer-profiles/dev-profile-incident/):

- [`README.md`](deploy/docker/developer-profiles/dev-profile-incident/README.md) — human-facing profile guide: decisions, rationale, what ships when (MVP1/MVP2), dev/deploy workflows, and status. Start here.
- [`.docs/incident-plan-implementation-local.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/incident-plan-implementation-local.md) / [`.docs/incident-plan-implementation-remote.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/incident-plan-implementation-remote.md) — AI/implementer-facing, split by LLM/VLM deployment mode (local NIM containers vs. NGC-hosted remote): profile setup, GPU topology, dev/deploy guide, NVIDIA stock-profile reference.
- [`.docs/incident-plan-implementation-shared.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/incident-plan-implementation-shared.md) — AI/implementer-facing, deployment-mode-independent: Postgres, R2, frontend, API, feature implementation, engineering evaluation, resulting directory tree.

When working on this project, read the profile README first, then whichever Implementation doc(s) match the task.

Other services in this repo have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## incident-console Postgres schema

`deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py` defines a 12-table-plus-matches
schema supporting multiple model runs over the same video plus a parallel human ground-truth set (see its module
docstring for the full table list and the `review_status` design note). `db.py` is the authoritative source for
this schema; the planning docs under `deploy/docker/developer-profiles/dev-profile-incident/.docs/` were reconciled with it in PR #24 (the shared implementation doc's §1 table sketch predates the built schema and is kept only as a rough map - do not design from it). Identity rule: 1 video = 1 incident (`incidents.incident_id` ==
`videos.id`, no separate `video_id` column). Fixture data in `deploy/docker/developer-profiles/dev-profile-incident/incident-console/fixtures/data/*.csv`
(72 rows on disk, 36 real + 36 synthetic `SYN-`-prefixed placeholders with no matching R2 video) is the seed source for the Postgres importer
(`deploy/docker/developer-profiles/dev-profile-incident/incident-console/scripts/seed_supabase.py` via `scripts/seed_data.py`), which drops the `SYN-`-prefixed rows and seeds only the
36 real incidents under one shared `model_run_id`. The console is database-backed only; there is no offline
CSV-preview UI mode.

`services/agent/src/vss_agents/utils/incident_db.py` is the agent-side counterpart: an async Supabase
PostgREST CRUD helper (`supabase-py`'s `AsyncClient`/`acreate_client`, not `asyncpg`/direct-Postgres) against
the same schema, mirroring `db.py`'s tables/columns for the subset an agent-side caller plausibly writes
(videos/model_runs/incidents/entities/instruments/assets/reports/review_status/notifications; the `gt_*` and
`*_matches` tables stay console/eval-only). Config is `INCIDENT_SUPABASE_URL` / `INCIDENT_SUPABASE_SERVICE_ROLE_KEY`
(deliberately NOT `INCIDENT_DB_DSN`, which stays owned by the console's own `db.py`); unset means the feature is
unavailable, no fallback. This split exists because the deployment VM (`kwanz-ws`) DPI-blocks raw Postgres wire
protocol on port 5432, so only the HTTPS-based PostgREST route works for the agent from there - a direct-Postgres
driver on the agent side breaks Analyze on `kwanz-ws`. PostgREST has no client-held transactions or
`SELECT ... FOR UPDATE`; the one operation needing atomicity (`insert_incident`'s delete-then-insert plus
`review_status` reset) calls the `insert_incident` Postgres RPC function (`deploy/docker/developer-profiles/dev-profile-incident/supabase/migrations/`) via
`/rpc/insert_incident` instead (see [`deploy/docker/developer-profiles/dev-profile-incident/supabase/README.md`](deploy/docker/developer-profiles/dev-profile-incident/supabase/README.md) for how to apply it via `supabase db push`).

## incident-console-v2 real-VST R2 upload fallback

Real VST/NvStreamer's chunk-upload response never includes a durable R2 object key (`filePath`) — only
`mock-backend`'s own reimplementation (`vst_storage.py`) fakes that field by doing its own R2 upload. Since
`incident-console-v2`'s analysis flow (`app/api/analysis/route.ts`) hard-requires that key, `components/analysis-workspace.tsx`
checks the chunk-upload response for a valid key and, when missing (the real-VST case), uploads the file itself
through a new server-side-only route, `app/api/uploads/r2/route.ts` (R2 `PutObject` via `lib/r2/config.ts`'s
`putR2Video`, reusing the same client pattern as `createR2PlaybackUrl`/`deleteR2Video`), and uses its returned key
going forward. This is v2-only and does not touch `vss-agent` or `mock-backend`; the existing VST chunked-upload
flow for obtaining `sensorId` (`lib/upload/chunked-upload.ts`) is unchanged.

## incident-console agent upload contract

`agent_client.py`'s `upload_video()` (in `deploy/docker/developer-profiles/dev-profile-incident/incident-console/`)
implements vss-agent's 3-step upload (`POST /api/v1/videos` → chunked POST to nvstreamer → `POST /api/v1/videos/{sensor_id}/complete`).
The chunk POST must use form field `mediaFile` plus a separate `filename` field (`services/ui/packages/common/lib-src/utils/chunkedUpload.ts`'s
`formData.append('mediaFile', chunk, fileName)` / `formData.append('filename', fileName)`) — an
earlier version sent field `file` with no `filename`, which both the real VST endpoint and
`mock-backend/base_profile_mock` silently ignore (empty body, fallback filename). Neither backend's
`/complete` response carries a playable URL — `upload_video()` reads the chunk response's `filePath`
field instead, since `sensor_id` alone is not durable enough to serve as `videos.id` (`String(20)`,
but the agent's own sensor-id validation allows up to 128 chars): see `catalog_actions.derive_video_id()`
for the id it derives instead, and `pages/2_Report_Review.py` (which consolidates video upload and automatic
report generation via `catalog_actions.upload_and_record()` and `analyze_incident()`; the separate `1_Catalog.py`
page was removed) for the UI built on it.

## incident-console Report Review lazy previews

`pages/2_Report_Review.py`'s incident library fetches a video preview only when the reviewer clicks
"Load preview" on that card (state in `st.session_state`, rendering scoped to an `st.fragment` so the
click reruns only that card). This exists because Streamlit mounts and executes whatever a run
renders even inside a collapsed `st.expander` or an unselected `st.tabs` tab — visually hiding content
does not defer fetching it, which must be confirmed with a real browser's network panel, not assumed.
Apply the same `st.fragment` + `st.session_state` opt-in pattern to any future per-row expensive
content on this page; see `card_preview()`'s docstring and the "lazy about video" note in
`incident-console/README.md` for detail.

## Shell dotfiles/QoL bootstrap for kwanz-ws

[`deploy/docker/developer-profiles/dev-profile-incident/.dotfiles/`](deploy/docker/developer-profiles/dev-profile-incident/.dotfiles/README.md) is a personal, opt-in bash bootstrap for the shared
`kwanz-ws` VM (starship, fzf/ripgrep/bat/btop, per-account git-delta, and generic QoL aliases only — `bat`,
`vim=nvim`, `cat=bat`, `htop=btop`). It is not mandatory team-wide provisioning and does not touch
other accounts. The VSS deploy-lifecycle commands that used to be `aliases.sh` aliases/functions
(`mdx-ps`, `mdx-down`, `mdx-health`, `mdx-tunnel-incident`, `mdx-tunnel-incident-check`, `mdx-logs`,
`mdx-disk`, `mdx-rebuild-svc`, `mdx-rebuild`, `mdx-clean-datalog`, `ngc-env-on`, `gpu`) moved to
standalone executable scripts under
`deploy/docker/developer-profiles/dev-profile-incident/.scripts/` (`status.sh`, `down.sh`, `health.sh`,
`tunnel.sh`, `tunnel-check.sh`, `logs.sh`, `disk.sh`, `rebuild-svc.sh`, `rebuild.sh`,
`clean-datalog.sh`, `ngc-env.sh`, `gpu.sh`, `resolve-ssh-target.sh`). `start.sh` (at the top level of
`dev-profile-incident/`, alongside `local-start.sh`) is the laptop-side one-command daily
entry point: checks the VM deploy state over SSH, deploys the backend fresh if nothing is running
(direct compose with `generated.env.remote` — `dev-profile.sh` has no `incident` profile), stops on
a partial deploy, backgrounds the tunnel, then runs the local console. The VM-side scripts wrap the
project's own canonical deploy scripts (`dev-profile.sh`, `cleanup_all_datalog.sh`) rather than
hardcoding raw `docker`/`docker compose` invocations — see each script's header for the doc it is
grounded in. `.scripts/tunnel.sh`, `.scripts/tunnel-check.sh`, and top-level `start.sh` are laptop-side only
(SSH tunnel from laptop to the VM backend for the locally-run incident-console); never run them on kwanz-ws itself.

`vss-agent` and the analytics modules (`video-analytics-api`, `behavior-analytics`) run as native
processes on `kwanz-ws` rather than Docker containers, managed by `.scripts/native-services.sh`
(`start`/`stop`/`restart`/`status`/`logs`, PID files and logs under `/srv/rise-up/vss/.run/`); VIOS/VST
media engines and backing infra (Postgres, Redis, Phoenix, HAProxy) stay in Docker.
`.scripts/prune-native-images.sh` removes the Docker images those native services no longer need. See
`dev-profile-incident/README.md`'s "Native vs. Docker service split" section for the full picture.

## UI development without GPU/NIM containers

[`deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the entire `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) behind one FastAPI process, so `services/ui/apps/nv-metropolis-bp-vss-ui` can be run and clicked through unmodified with zero GPU, zero NIM containers, and no VM deployment. See its README for run instructions and the `NEXT_PUBLIC_*` env vars to point the real UI at it. Its sibling `search_profile_mock/` is the `bp_developer_search` superset (port 7778). A `mock-backend/mock_data/` Postgres-schema mock for the incident-console was once planned but does not exist; do not conflate it with these.

## Automatic environment setup (git hooks)

[`.githooks/`](.githooks/README.md) propagates untracked `.env` files from the main worktree into new/checked-out worktrees (copy-if-missing, never overwrites, `generated.env` excluded), copies the main worktree's real `dev-profile-incident/.env.local` into a new worktree (also replacing a leftover placeholder copy; seeds from the tracked `.env` template only when the main worktree has none), self-heals the three `.env.local -> ../.env.local` symlinks (`incident-console`, `incident-console-v2`, `vlm-gateway`), and keeps the incident-console `uv` venv in sync (`uv sync`, skipped when `.venv` is newer than `pyproject.toml`/`uv.lock`). Fires on checkout/switch/worktree-add (post-checkout), merge/pull (post-merge) and rebase/amend (post-rewrite). Activation is per-clone local config, so every fresh clone (laptop, VM) must run `.githooks/activate.sh` once. Out of scope there: `.ngc_env` and R2 config (separate phases).

## incident-console Tier 1 GT evaluation

In `deploy/docker/developer-profiles/dev-profile-incident/incident-console/`, `eval_gt.py` scores one model run's `incidents`/`entities`/`instruments`/`assets` against the parallel
`gt_*` tables (type/severity exact match, an LLM-judge score for description via `INCIDENT_LLM_BASE_URL`,
tolerance comparisons for timestamps/duration, and TP/FP/FN/P/R/F1 derived from `matching.py`'s existing
embedding+Hungarian output - `matching.py` itself is untouched). `run_evaluation(db, incident_id,
model_run_id)` is the one orchestration entry point; `report_detail.py`'s "Ground-truth evaluation" section
(shown only when a `gt_incidents` row exists for that incident) calls it via `DBReports.run_gt_evaluation()`
and renders the result - no new page. `mock_llm_server.py` provides the `/v1/embeddings` and judge-branched `/v1/chat/completions`
routes this needs with zero live infra; `scripts/seed_gt_demo.py` seeds a 5-incident demo set (real
CSV-fixture ground truth + a perturbed model run under `MR-EVAL-DEMO`) covering every required scenario.
See [`incident-console/README.md`](deploy/docker/developer-profiles/dev-profile-incident/incident-console/README.md)'s "Tier 1 GT evaluation" section for the exact local run commands.

## incident-console DB connection contract

`IncidentDB` (`incident-console/db.py`) has two engines; `incident-console/db_connection.py`'s docstring is the
authority. Writes use `self.engine.begin()` (transactional). Reads use `self.read_engine.connect()`: a separate
AUTOCOMMIT engine with its own pool that refuses write statements, one wire round trip per query instead of four.
Never make AUTOCOMMIT global (not atomic), and do not enable it per checkout (two round trips). Every public
`IncidentDB` method is replayed once after a dropped connection unless a COMMIT was attempted, so keep methods free
of non-database side effects. Anything counting statements or checkouts must listen on `handle.engines` (both
pools). `scripts/measure_db_roundtrips.py` measures round trips on a disposable Postgres; `scripts/db_timing.py` times
a real DSN without printing secrets. Hyperdrive is Workers-only and does not apply to this Streamlit app.

## incident-console Dashboard evidence path

Never query per incident inside a page loop: over psycopg2 every `engine.connect()` also pays a pre-ping, `BEGIN` and
`ROLLBACK` round trip, so the old Dashboard loop cost ~440 server round trips per rerun (~14 s at 30 ms RTT on a real
Postgres). In `deploy/docker/developer-profiles/dev-profile-incident/incident-console/`, `IncidentDB.list_evidence_batch`
(`db.py`) fetches all evidence in 3 statements on the read-only engine (`self.read_engine`, consistent with every
other read method - see "incident-console DB connection contract" above) and matches `(incident_id, model_run_id)`
pairs - batching on `incident_id` alone mixes an incident's model runs. `dashboard_data.py` caches it (`st.cache_data`,
30 s TTL); anything that rewrites evidence rows must call its `clear_evidence_cache()` (see
`catalog_actions.analyze_and_refresh`). The incident list stays uncached. See the README's "Dashboard query cost" for
`scripts/bench_dashboard_queries.py`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
