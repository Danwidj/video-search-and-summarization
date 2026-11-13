# Agent Notes

## Project overview & architecture

This repository is a fork of [NVIDIA's VSS Blueprint](https://docs.nvidia.com/vss/latest/index.html) — GPU-accelerated video AI agents (search, summarization, visual Q&A, alert verification) built from vision-language models, RAG, and NVIDIA NIM microservices. See the root [`README.md`](README.md) for workflows, agent architecture, and the repository structure overview.

- **Compose profile architecture:** [`deploy/docker/README.md`](deploy/docker/README.md) is authoritative. Developer stacks run via `deploy/docker/scripts/dev-profile.sh up --profile <base|lvs|alerts|search> --hardware-profile <...>`, not hand-edited Compose.
- **Deployment topology:**
  - **Full GPU-backed stack** (NIM containers, real inference): VM-only, brought up via `dev-profile.sh` (stock profiles) or direct `docker compose` (this fork's `incident` profile). Requires `NGC_CLI_API_KEY` and a GPU-equipped host.
  - **Zero-GPU local mock (a backup that mimics the backend):** [`mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the whole `bp_developer_base` backend (vss-agent API + VIOS/VST + inference) behind one FastAPI process on port 7777. It is a mock, not the real backend: run and verify frontend work (`services/ui/apps/nv-metropolis-bp-vss-ui`, `incident-console-v2`) on the VM, not here. There is no mock of the Postgres schema (do not conflate the two); the SQL harness in [`supabase/tests/`](deploy/docker/developer-profiles/dev-profile-incident/supabase/README.md) tests the real schema on a throwaway local Postgres.

Other services have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## Incident Search & Reporting Capstone (Daniel's team)

This fork adds a video-driven incident search and reporting system (sponsored by NVIDIA NVAITC) under [`deploy/docker/developer-profiles/dev-profile-incident/`](deploy/docker/developer-profiles/dev-profile-incident/). It is laid out like NVIDIA's own agent docs:

- **Code changes:** [`dev-profile-incident/AGENTS.md`](deploy/docker/developer-profiles/dev-profile-incident/AGENTS.md) has the components, checks, architecture rules, boundaries, the standing docs rule and a map of `.docs/`. Read it before touching anything in the profile, including its `services/agent` incident code.
- **Operating the profile:** [`dev-profile-incident/skills/`](deploy/docker/developer-profiles/dev-profile-incident/skills/README.md) holds the agentskills.io skills (`incident-search` among them). UI work in `incident-console-v2` should read the `shadcn` skill first. Claude Code loads them automatically through the symlinks in [`.claude/skills/`](.claude/skills/).
- **Background facts:** [`dev-profile-incident/.docs/`](deploy/docker/developer-profiles/dev-profile-incident/.docs/).
- **Never** deploy or tear down this profile with `dev-profile.sh` or NVIDIA's `vss-deploy-profile` skill. Use `start.sh` and the `incident-*` skills.

**Standing docs rule:** update [`.docs/`](deploy/docker/developer-profiles/dev-profile-incident/.docs/) and affected `incident-*` skill(s) in the same change whenever behaviour, contracts, schemas, commands, layout or status that the docs describe change. Skip docs only when the user explicitly says not to. The table in the profile `AGENTS.md` says which file to update. Stale docs are a defect, not a follow-up.

## Environment Pointers

- **Run and verify on the VM:** run all UI and backend work with `./start.sh --mode vm` against the VM's vss-agent, never `--mode mock`. If the VM is unreachable, stop and report it; do not fall back to mock. The mock backend is a mock that mimics the backend, not the real one.
- **Automatic environment setup:** [`.githooks/`](.githooks/README.md) keeps untracked `.env` files, `.env.local` copies and the incident profile's `.env.local` symlinks in sync across worktrees. Run `.githooks/activate.sh` once per clone.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
