# Agent Notes

## Project overview & architecture

This repository is a fork of [NVIDIA's VSS Blueprint](https://docs.nvidia.com/vss/latest/index.html) — GPU-accelerated video AI agents (search, summarization, visual Q&A, alert verification) built from vision-language models, RAG, and NVIDIA NIM microservices. See the root [`README.md`](README.md) for workflows, agent architecture, and the repository structure overview.

- **Compose profile architecture:** [`deploy/docker/README.md`](deploy/docker/README.md) is authoritative. Developer stacks run via `deploy/docker/scripts/dev-profile.sh up --profile <base|lvs|alerts|search> --hardware-profile <...>`, not hand-edited Compose.
- **Deployment topology:**
  - **Full GPU-backed stack** (NIM containers, real inference): VM-only, brought up via `dev-profile.sh` (stock profiles) or direct `docker compose` (this fork's `incident` profile). Requires `NGC_CLI_API_KEY` and a GPU-equipped host.
  - **Zero-GPU local mock:** [`mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the whole `bp_developer_base` backend (vss-agent API + VIOS/VST + inference) behind one FastAPI process on port 7777, so frontend work (`services/ui/apps/nv-metropolis-bp-vss-ui`, `incident-console-v2`) runs locally without GPU or NIM containers. Sibling `mock-backend/search_profile_mock/` (port 7778) covers `bp_developer_search`.

Other services have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## Incident Search & Reporting Capstone (Daniel's team)

This fork adds a video-driven incident search and reporting system (sponsored by NVIDIA NVAITC) under [`deploy/docker/developer-profiles/dev-profile-incident/`](deploy/docker/developer-profiles/dev-profile-incident/). It is laid out like NVIDIA's own agent docs:

- **Code changes:** [`dev-profile-incident/AGENTS.md`](deploy/docker/developer-profiles/dev-profile-incident/AGENTS.md) has the components, checks, architecture rules, boundaries, the standing docs rule and a map of `.docs/`. Read it before touching anything in the profile, including its `services/agent` incident code.
- **Operating the profile:** [`dev-profile-incident/skills/`](deploy/docker/developer-profiles/dev-profile-incident/skills/README.md) holds agentskills.io skills (`incident-start`, `incident-operate-vm`, `incident-analyze-video`, `incident-manage-database`, `incident-run-eval`). Claude Code loads them automatically through the symlinks in [`.claude/skills/`](.claude/skills/).
- **Background facts:** [`dev-profile-incident/.docs/`](deploy/docker/developer-profiles/dev-profile-incident/.docs/). Start with `status.md`.
- **Never** deploy or tear down this profile with `dev-profile.sh` or NVIDIA's `vss-deploy-profile` skill. Use `start.sh` and the `incident-*` skills.

**Standing docs rule:** any change under `dev-profile-incident/` updates the affected `.docs/` file(s) and `incident-*` skill(s) in the same PR, and any architectural or tooling decision adds a `.docs/decisions.md` entry. The table in the profile `AGENTS.md` says which file to update. Stale docs are a defect, not a follow-up.

## Environment Pointers

- **Zero-GPU UI work:** see [`mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) for the mock server. There is no mock of the Postgres schema (do not conflate the two).
- **Automatic environment setup:** [`.githooks/`](.githooks/README.md) keeps untracked `.env` files, `.env.local` copies, symlinks and `uv` virtual environments in sync across worktrees. Run `.githooks/activate.sh` once per clone.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
