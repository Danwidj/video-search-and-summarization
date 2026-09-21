# Agent Notes

## Incident Search & Reporting Capstone (Daniel's team)

A video-driven incident search and reporting system is being built on this VSS blueprint fork, sponsored by NVIDIA NVAITC. The profile README and technical reference docs live under [`deploy/docker/developer-profiles/dev-profile-incident/`](deploy/docker/developer-profiles/dev-profile-incident/):

- [`README.md`](deploy/docker/developer-profiles/dev-profile-incident/README.md) — human-facing profile guide: decisions, rationale, what ships when (MVP1/MVP2), dev/deploy workflows, and status. Start here.
- [`incident-plan/incident-plan-implementation-local.md`](deploy/docker/developer-profiles/dev-profile-incident/incident-plan/incident-plan-implementation-local.md) / [`incident-plan/incident-plan-implementation-remote.md`](deploy/docker/developer-profiles/dev-profile-incident/incident-plan/incident-plan-implementation-remote.md) — AI/implementer-facing, split by LLM/VLM deployment mode (local NIM containers vs. NGC-hosted remote): profile setup, GPU topology, dev/deploy guide, NVIDIA stock-profile reference.
- [`incident-plan/incident-plan-implementation-shared.md`](deploy/docker/developer-profiles/dev-profile-incident/incident-plan/incident-plan-implementation-shared.md) — AI/implementer-facing, deployment-mode-independent: Postgres, R2, frontend, API, feature implementation, engineering evaluation, resulting directory tree.

When working on this project, read the profile README first, then whichever Implementation doc(s) match the task.

Other services in this repo have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## incident-console Postgres schema

`deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py` defines a 12-table-plus-matches
schema supporting multiple model runs over the same video plus a parallel human ground-truth set (see its module
docstring for the full table list and the `review_status` design note). `db.py` is the authoritative source for
this schema; the planning docs under `deploy/docker/developer-profiles/dev-profile-incident/incident-plan/` were reconciled with it in PR #24 (the shared implementation doc's §1 table sketch predates the built schema and is kept only as a rough map - do not design from it). Identity rule: 1 video = 1 incident (`incidents.incident_id` ==
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

## Shell dotfiles/QoL bootstrap for kwanz-ws

[`deploy/docker/developer-profiles/dev-profile-incident/dotfiles/`](deploy/docker/developer-profiles/dev-profile-incident/dotfiles/README.md) is a personal, opt-in bash bootstrap for the shared
`kwanz-ws` VM (starship, fzf/ripgrep/bat/btop, tmux config, and generic QoL aliases only — `bat`,
`vim=nvim`, `cat=bat`, `htop=btop`). It is not mandatory team-wide provisioning and does not touch
other accounts. The VSS deploy-lifecycle commands that used to be `aliases.sh` aliases/functions
(`mdx-ps`, `mdx-down`, `mdx-health`, `mdx-tunnel-incident`, `mdx-tunnel-incident-check`, `mdx-logs`,
`mdx-disk`, `mdx-rebuild-svc`, `mdx-rebuild`, `mdx-clean-datalog`, `ngc-env-on`, `gpu`) moved to
standalone executable scripts under
`deploy/docker/developer-profiles/dev-profile-incident/scripts/` (`status.sh`, `down.sh`, `health.sh`,
`tunnel.sh`, `tunnel-check.sh`, `logs.sh`, `disk.sh`, `rebuild-svc.sh`, `rebuild.sh`,
`clean-datalog.sh`, `ngc-env.sh`, `gpu.sh`, `resolve-ssh-target.sh`). `start.sh` (at the top level of
`dev-profile-incident/`, alongside `local-start.sh`) is the laptop-side one-command daily
entry point: checks the VM deploy state over SSH, deploys the backend fresh if nothing is running
(direct compose with `generated.env.remote` — `dev-profile.sh` has no `incident` profile), stops on
a partial deploy, backgrounds the tunnel, then runs the local console. The VM-side scripts wrap the
project's own canonical deploy scripts (`dev-profile.sh`, `cleanup_all_datalog.sh`) rather than
hardcoding raw `docker`/`docker compose` invocations — see each script's header for the doc it is
grounded in. `scripts/tunnel.sh`, `scripts/tunnel-check.sh`, and top-level `start.sh` are laptop-side only
(SSH tunnel from laptop to the VM backend for the locally-run incident-console); never run them on kwanz-ws itself.

`vss-agent` and the analytics modules (`video-analytics-api`, `behavior-analytics`) run as native
processes on `kwanz-ws` rather than Docker containers, managed by `scripts/native-services.sh`
(`start`/`stop`/`restart`/`status`/`logs`, PID files and logs under `/srv/rise-up/vss/.run/`); VIOS/VST
media engines and backing infra (Postgres, Redis, Phoenix, HAProxy) stay in Docker.
`scripts/prune-native-images.sh` removes the Docker images those native services no longer need. See
`dev-profile-incident/README.md`'s "Native vs. Docker service split" section for the full picture.

## UI development without GPU/NIM containers

[`deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the entire `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) behind one FastAPI process, so `services/ui/apps/nv-metropolis-bp-vss-ui` can be run and clicked through unmodified with zero GPU, zero NIM containers, and no VM deployment. See its README for run instructions and the `NEXT_PUBLIC_*` env vars to point the real UI at it. This is unrelated to the sibling `deploy/docker/developer-profiles/dev-profile-incident/mock-backend/mock_data/` module (a different, not-yet-built Postgres schema mock for the incident-console app above).

## Automatic environment setup (git hooks)

[`.githooks/`](.githooks/README.md) propagates untracked `.env` files from the main worktree into new/checked-out worktrees (copy-if-missing, never overwrites, `generated.env` excluded) and keeps the incident-console `uv` venv in sync (`uv sync`, skipped when `.venv` is newer than `pyproject.toml`/`uv.lock`). Fires on checkout/switch/worktree-add (post-checkout), merge/pull (post-merge) and rebase/amend (post-rewrite). Activation is per-clone local config, so every fresh clone (laptop, VM) must run `.githooks/activate.sh` once. Out of scope there: `.ngc_env` and R2 config (separate phases).

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

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
