# Agent Notes

## Incident Search & Reporting Capstone (Daniel's team)

A video-driven incident search and reporting system is being built on this VSS blueprint fork, sponsored by NVIDIA NVAITC. Planning docs live in [`docs/incident-plan/`](docs/incident-plan/):

- [`incident-plan-overview.md`](docs/incident-plan/incident-plan-overview.md) — human-facing: decisions, rationale, what ships when (MVP1/MVP2), copy-paste deploy commands. Start here.
- [`incident-plan-implementation-local.md`](docs/incident-plan/incident-plan-implementation-local.md) / [`incident-plan-implementation-remote.md`](docs/incident-plan/incident-plan-implementation-remote.md) — AI/implementer-facing, split by LLM/VLM deployment mode (local NIM containers vs. NGC-hosted remote): profile setup, GPU topology, dev/deploy guide, NVIDIA stock-profile reference.
- [`incident-plan-implementation-shared.md`](docs/incident-plan/incident-plan-implementation-shared.md) — AI/implementer-facing, deployment-mode-independent: Postgres, R2, frontend, API, feature implementation, engineering evaluation, resulting directory tree.

When working on this project, read the Overview doc first, then whichever Implementation doc(s) match the task.

Other services in this repo have their own `AGENTS.md` (e.g. [`services/agent/AGENTS.md`](services/agent/AGENTS.md)) — consult those when touching that service directly.

## UI development without GPU/NIM containers

[`deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/`](deploy/docker/developer-profiles/dev-profile-incident/mock-backend/base_profile_mock/README.md) mocks the entire `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference) behind one FastAPI process, so `services/ui/apps/nv-metropolis-bp-vss-ui` can be run and clicked through unmodified with zero GPU, zero NIM containers, and no VM deployment. See its README for run instructions and the `NEXT_PUBLIC_*` env vars to point the real UI at it. This is unrelated to the sibling `deploy/docker/developer-profiles/dev-profile-incident/mock-backend/mock_data/` module (a different, not-yet-built Postgres schema mock for the incident-console app above).

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
