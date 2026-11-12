<!--
agents:
  read-when: Choosing an incident skill, or adding, moving or renaming one.
  owns: the skill catalogue and the rules for writing a skill.
  rules: A skill owns procedure only; put facts in .docs/ and link to them. Add the repo-root .claude/skills symlink and update the root README index in the same change.
-->

# Incident skills

Agent skills for operating the incident profile from natural language: start the stack, analyse a clip, apply a migration, run the benchmark. Each folder is one skill in the [agentskills.io](https://agentskills.io/specification) format, modelled on NVIDIA's [skills](../../../../../skills/README.md). They are not coding guidance; to change code, read [AGENTS.md](../AGENTS.md).

## What is inside

| I want to | Use this skill |
|---|---|
| Set up secrets and launch the console, against the VM or the mock | [incident-start](incident-start/SKILL.md) |
| Deploy, restart, inspect or fix services on the VM | [incident-operate-vm](incident-operate-vm/SKILL.md) |
| Upload a clip, then generate, re-run, version or mark official an incident report | [incident-analyze-video](incident-analyze-video/SKILL.md) |
| Search incident evidence, ask grounded follow-up questions, refresh evidence crops | [incident-search](incident-search/SKILL.md) |
| Change or inspect the Supabase schema, apply a migration, query incident data, find a video in R2 | [incident-manage-database](incident-manage-database/SKILL.md) |
| Ingest ground truth, run the P1/RP1 benchmark, aggregate results | [incident-run-eval](incident-run-eval/SKILL.md) |
| Build, style or migrate UI with shadcn/ui and Tailwind (read first for `incident-console-v2`) | [shadcn](shadcn/SKILL.md) |

## Pick between look-alikes

- `incident-start` launches from the laptop; `incident-operate-vm` changes the backend on the VM. `start.sh --mode vm` heals the VM itself, so use the second only when that fails.
- `incident-analyze-video` produces one report; `incident-run-eval` scores many predictions against ground truth.
- `incident-manage-database` owns the schema and storage layout; `incident-analyze-video` owns the rows one analysis writes.
- NVIDIA's `vss-deploy-profile` drives `dev-profile.sh`, which does not know this profile. Never use it to deploy or tear down the incident profile.

## Install a skill

Claude Code needs no install step: [.claude/skills/](../../../../../.claude/skills/) at the repo root holds a symlink to each skill folder, so a session in this repo loads them. Other agentskills.io hosts (Codex, Cursor) use NVIDIA's install prompt with this folder. The shadcn skill is also linked from [.agents/skills/](../../../../../.agents/skills/).

## Add a skill

1. Create `skills/<name>/SKILL.md` here. This folder is the source of truth.
2. Link it: `ln -s ../../deploy/docker/developer-profiles/dev-profile-incident/skills/<name> .claude/skills/<name>` from the repo root.
3. Make `name` in the frontmatter match the folder, say when to use the skill and when not to, and keep `license` and `metadata`.
4. Add it to the table above and to the root [README](../README.md) index.

## Rules

- Put facts in `.docs/` and link to them; a skill holds only steps, commands, gates and checks.
- When a command, port, script or contract changes, update the affected skill in the same PR as the `.docs/` change.
- These skills have no evals: NVIDIA's skills CI covers only the root `skills/**`.

## Read more

- [Operations runbook](../.docs/incident-profile-operations.md): what runs on the VM
- [Architecture: Launch modes and connectivity](../.docs/architecture.md#launch-modes-and-connectivity): mock against vm
- [Search spec](../.docs/mvp2/README.md): the contracts behind `incident-search`
- NVIDIA's [vss-search-archive](../../../../../skills/vss-search-archive/SKILL.md) skill: the upstream search reference
