# Agent Notes

## Project overview & architecture

This repository is a fork of [NVIDIA's VSS Blueprint](https://docs.nvidia.com/vss/latest/index.html) — GPU-accelerated video AI agents (search, summarization, visual Q&A, alert verification) built from vision-language models, RAG, and NVIDIA NIM microservices. See the root [`README.md`](README.md) for workflows, agent architecture, and the repository structure overview.

- **Compose profile architecture:** [`deploy/docker/README.md`](deploy/docker/README.md) is authoritative. Developer stacks run via `deploy/docker/scripts/dev-profile.sh up --profile <base|lvs|alerts|search> --hardware-profile <...>`, not hand-edited Compose.
- **Deployment topology:**
  - **Full GPU-backed stack** (NIM containers, real inference): VM-only, brought up via `dev-profile.sh` (stock profiles) or direct `docker compose` (this fork's `incident` profile). Requires `NGC_CLI_API_KEY` and a GPU-equipped host.
  - **Zero-GPU local mock:** [`mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the whole `bp_developer_base` backend (vss-agent API + VIOS/VST + inference) behind one FastAPI process on port 7777, so frontend work (`services/ui/apps/nv-metropolis-bp-vss-ui`, `incident-console-v2`) runs locally without GPU or NIM containers. Sibling `mock-backend/search_profile_mock/` (port 7778) covers `bp_developer_search`.

Other services have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## Incident Search & Reporting Capstone (Daniel's team)

A video-driven incident search and reporting system is being built on this VSS blueprint fork, sponsored by NVIDIA NVAITC. The profile README and technical reference docs live under [`deploy/docker/developer-profiles/dev-profile-incident/`](deploy/docker/developer-profiles/dev-profile-incident/):

- [`README.md`](deploy/docker/developer-profiles/dev-profile-incident/README.md) — Short human entry point: doc index and setup steps. Start here.
- [`.docs/action-plan.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/action-plan.md) — Goals, MVP1 & MVP2 scope, success criteria, and verifiable status.
- [`.docs/status.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/status.md) — Current implementation status, outstanding items, known issues, and live VM configuration snapshot.
- [`.docs/architecture.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/architecture.md) — System context, component tables, deployment topologies, and upload/analyze/search sequence diagrams.
- [`.docs/data.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/data.md) — Supabase PostgreSQL schema (ERD & table specs), Cloudflare R2 bucket layout, and documented data quirks.
- [`.docs/analysis-schema.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/analysis-schema.md) — Reference incident report format (agent `snake_case`), field specs, and console/gateway translation mapping.
- [`.docs/incident-profile-operations.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/incident-profile-operations.md) — AI/implementer-facing operational facts: environments, native vs Docker split, SSH troubleshooting, deploy runbook, and verification checklist.
- [`.docs/decisions.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/decisions.md) — Chronological architectural and tooling decision log with context, alternatives, and citations.
- [`.docs/archive/`](deploy/docker/developer-profiles/dev-profile-incident/.docs/archive/) — Retired local deployment and legacy plan documents preserved for reference.

When working on this project, read the profile README first, then whichever `.docs/` document(s) match the task.

**Standing docs rule:** Any change under `deploy/docker/developer-profiles/dev-profile-incident/` (code, scripts, config, deployment, env/secrets layout, architecture) must update the affected `.docs/` file(s) in the same PR — `.docs/action-plan.md` for scope/milestones, `.docs/status.md` for implementation status or known issues, `.docs/architecture.md` for topology/diagrams/components, `.docs/data.md` for database schema or R2 storage changes, `.docs/analysis-schema.md` for report model/field translation changes, and `.docs/incident-profile-operations.md` for runtime/deploy/troubleshooting facts — and keep the profile README's doc index accurate if a doc is added, moved, or renamed. Any PR making an architectural or tooling decision must also add an entry to `.docs/decisions.md`. Stale docs are a defect, not a follow-up.

## Component & Environment Pointers

- **Incident Console v2 (Next.js):** Active frontend under [`incident-console-v2/`](deploy/docker/developer-profiles/dev-profile-incident/incident-console-v2/README.md), including the real-VST R2 upload fallback.
- **Incident Console v1 (Streamlit, retired):** Implementation notes (v1 schema, upload contract, lazy previews, GT eval, DB connection contract, evidence batching) are in [`incident-console/README.md`](deploy/docker/developer-profiles/dev-profile-incident/incident-console/README.md); shared DB truth, PostgREST CRUD helper, and VM DPI blocking are in [`.docs/data.md`](deploy/docker/developer-profiles/dev-profile-incident/.docs/data.md).
- **Shell Dotfiles & Deploy Scripts:** VM dotfiles bootstrap in [`.dotfiles/`](deploy/docker/developer-profiles/dev-profile-incident/.dotfiles/README.md), standalone deploy scripts in [`.scripts/`](deploy/docker/developer-profiles/dev-profile-incident/.scripts/README.md), and daily laptop launcher [`start.sh`](deploy/docker/developer-profiles/dev-profile-incident/start.sh).
- **UI Mocking (Zero GPU/NIM):** See [`mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) for the mock server; a mock-data Postgres-schema mock does not exist (do not conflate).
- **Automatic Environment Setup:** [`.githooks/`](.githooks/README.md) synchronizes untracked `.env` files, `.env.local` copies, symlinks, and `uv` virtual environments across worktrees. Run `.githooks/activate.sh` once per clone.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
