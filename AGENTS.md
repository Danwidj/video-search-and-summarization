# Agent Notes

## Incident Search & Reporting Capstone (Daniel's team)

A video-driven incident search and reporting system is being built on this VSS blueprint fork, sponsored by NVIDIA NVAITC. Planning docs live in [`docs/incident-plan/`](docs/incident-plan/):

- [`incident-plan-overview.md`](docs/incident-plan/incident-plan-overview.md) — human-facing: decisions, rationale, what ships when (MVP1/MVP2), copy-paste deploy commands. Start here.
- [`incident-plan-implementation-local.md`](docs/incident-plan/incident-plan-implementation-local.md) / [`incident-plan-implementation-remote.md`](docs/incident-plan/incident-plan-implementation-remote.md) — AI/implementer-facing, split by LLM/VLM deployment mode (local NIM containers vs. NGC-hosted remote): profile setup, GPU topology, dev/deploy guide, NVIDIA stock-profile reference.
- [`incident-plan-implementation-shared.md`](docs/incident-plan/incident-plan-implementation-shared.md) — AI/implementer-facing, deployment-mode-independent: Postgres, R2, frontend, API, feature implementation, engineering evaluation, resulting directory tree.

When working on this project, read the Overview doc first, then whichever Implementation doc(s) match the task.

Other services in this repo have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## incident-console Postgres schema

`deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py` defines a 12-table-plus-matches
schema supporting multiple model runs over the same video plus a parallel human ground-truth set (see its module
docstring for the full table list and the `review_status` design note). `db.py` is the authoritative source for
this schema; the planning docs under `docs/incident-plan/` were reconciled with it in PR #24 (the shared implementation doc's §1 table sketch predates the built schema and is kept only as a rough map - do not design from it). Identity rule: 1 video = 1 incident (`incidents.incident_id` ==
`videos.id`, no separate `video_id` column). `fixtures/data/*.csv` (72 rows on disk, 36 real + 36 synthetic
`SYN-`-prefixed placeholders with no matching R2 video) is the seed source for the Postgres importer
(`scripts/seed_supabase.py` via `scripts/seed_data.py`), which drops the `SYN-`-prefixed rows and seeds only the
36 real incidents under one shared `model_run_id`. The console is database-backed only; there is no offline
CSV-preview UI mode.

`services/agent/src/vss_agents/utils/incident_db.py` is the agent-side counterpart: an async `asyncpg`
CRUD helper (pool sized `min_size=1, max_size=2`, since Hyperdrive already pools) against the same schema,
mirroring `db.py`'s tables/columns for the subset an agent-side caller plausibly writes
(videos/model_runs/incidents/entities/instruments/assets/reports/review_status/notifications; the `gt_*` and
`*_matches` tables stay console/eval-only). Config is `INCIDENT_DB_DSN`; unset means the feature is unavailable,
no fallback. Verified live against the real Hyperdrive-fronted Supabase Postgres: DSN/SSL connects with
`sslmode=require` (asyncpg reads it straight off the DSN's query string) and pooled queries work end to end under
`min_size=1, max_size=2` - see §1's "Verify live" bullet in
`docs/incident-plan/incident-plan-implementation-shared.md` for the full note, including the caveat that this
was a one-off smoke test, not a production concurrent-load test.

## incident-console agent upload contract

`agent_client.py`'s `upload_video()` implements vss-agent's 3-step upload (`POST /api/v1/videos` →
chunked POST to nvstreamer → `POST /api/v1/videos/{sensor_id}/complete`). The chunk POST must use
form field `mediaFile` plus a separate `filename` field (`services/ui/.../chunkedUpload.ts`'s
`formData.append('mediaFile', chunk, fileName)` / `formData.append('filename', fileName)`) — an
earlier version sent field `file` with no `filename`, which both the real VST endpoint and
`mock-backend/base_profile_mock` silently ignore (empty body, fallback filename). Neither backend's
`/complete` response carries a playable URL — `upload_video()` reads the chunk response's `filePath`
field instead, since `sensor_id` alone is not durable enough to serve as `videos.id` (`String(20)`,
but the agent's own sensor-id validation allows up to 128 chars): see `catalog_actions.derive_video_id()`
for the id it derives instead, and `pages/1_Catalog.py` for the upload/analyze/status-poll UI built on it.

## Shell dotfiles/QoL bootstrap for kwanz-ws

[`deploy/dotfiles/`](deploy/dotfiles/README.md) is a personal, opt-in bash bootstrap for the shared
`kwanz-ws` VM (starship, fzf/ripgrep/bat/btop, tmux config, and `mdx-*` deploy-lifecycle
aliases/functions). It is not mandatory team-wide provisioning and does not touch other accounts.
The `mdx-*` wrappers call the project's own canonical deploy scripts (`dev-profile.sh`,
`cleanup_all_datalog.sh`) rather than hardcoding raw `docker`/`docker compose` invocations —
see `deploy/dotfiles/aliases.sh`'s own comments for which script (or doc) grounds each one.
Exception: `mdx-tunnel-incident` / `mdx-tunnel-incident-check` in the same file are
laptop-side only (SSH tunnel from laptop to the VM backend for the locally-run
incident-console); never run them on kwanz-ws itself.

## UI development without GPU/NIM containers

[`deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the entire `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) behind one FastAPI process, so `services/ui/apps/nv-metropolis-bp-vss-ui` can be run and clicked through unmodified with zero GPU, zero NIM containers, and no VM deployment. See its README for run instructions and the `NEXT_PUBLIC_*` env vars to point the real UI at it. This is unrelated to the sibling `deploy/docker/developer-profiles/dev-profile-incident/mock-backend/mock_data/` module (a different, not-yet-built Postgres schema mock for the incident-console app above).

## Automatic environment setup (git hooks)

[`.githooks/`](.githooks/README.md) propagates untracked `.env` files from the main worktree into new/checked-out worktrees (copy-if-missing, never overwrites, `generated.env` excluded) and keeps the incident-console `uv` venv in sync (`uv sync`, skipped when `.venv` is newer than `pyproject.toml`/`uv.lock`). Fires on checkout/switch/worktree-add (post-checkout), merge/pull (post-merge) and rebase/amend (post-rewrite). Activation is per-clone local config, so every fresh clone (laptop, VM) must run `.githooks/activate.sh` once. Out of scope there: `.ngc_env` and R2 config (separate phases).

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
