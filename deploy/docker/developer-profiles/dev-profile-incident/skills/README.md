# Incident Profile Skills

Operational skills for `dev-profile-incident`, the incident search and reporting capstone built on the VSS blueprint. Each subdirectory is a self-contained skill in the [agentskills.io](https://agentskills.io/specification) format, modelled on NVIDIA's [`skills/`](../../../../../skills/README.md).

Like NVIDIA's skills, these are for **deploying and operating** the profile from natural language (start the stack, analyse a clip, apply a migration, run the eval). They are not coding guidance. For how to change code in this profile, read [`../AGENTS.md`](../AGENTS.md).

> **New here?** Read [Orientation](#orientation) and then [Which skill do I need?](#which-skill-do-i-need). Background facts live in [`../.docs/`](../.docs/). Skills link to those files instead of copying them.

---

## Orientation

```
  LAPTOP                                    kwanz-ws (shared GPU VM)
  ┌───────────────────────────┐ SSH tunnel  ┌──────────────────────────────┐
  │ incident-console-v2 :3200 │─8000, 7777─▶│ vss-agent :8000 (native)     │
  │                           │             │ HAProxy :7777 → VIOS/VST     │
  │ local mode only:          │             │ (Docker appliances)          │
  │   mock-backend  :7777     │             └──────────────┬───────────────┘
  │   vlm-gateway   :8600     │                            │
  └─────────────┬─────────────┘                            │
                ▼                                          ▼
  CLOUD:  Brev Switchyard (LLM/VLM) · Supabase (PostgREST + RPC) · Cloudflare R2 (videos)
```

Two ways to run it, both through [`start.sh`](../start.sh):

| Mode | Backend | Analysis path (`ANALYSIS_MODE`) | Needs |
|---|---|---|---|
| `--mode local` | `mock-backend` + `vlm-gateway` on the laptop | `gateway`: console calls the gateway, the console writes Supabase | `.env.local`, no GPU, no SSH |
| `--mode vm` (default) | Native `vss-agent` + Docker VIOS on `kwanz-ws` | `agent`: console calls `POST /api/v1/incidents/{id}/analyze`, both agent and console write Supabase | Tailscale, `Host kwanz-ws` SSH config, `.env.local` |

---

## Which skill do I need?

| I want to… | Use this skill |
|---|---|
| Set up secrets and launch the console, locally or against the VM | [`incident-start`](incident-start/SKILL.md) |
| Deploy, restart, inspect or fix services on `kwanz-ws` | [`incident-operate-vm`](incident-operate-vm/SKILL.md) |
| Upload a clip and generate, re-run, review or check an incident report | [`incident-analyze-video`](incident-analyze-video/SKILL.md) |
| Change or inspect the Supabase schema, apply a migration, find a video in R2 | [`incident-manage-database`](incident-manage-database/SKILL.md) |
| Ingest ground truth, run the P1/RP1 VLM benchmark, aggregate results | [`incident-run-eval`](incident-run-eval/SKILL.md) |
| Natural-language video search (MVP2) | Not built yet. See [`.docs/status.md`](../.docs/status.md). Upstream reference: [`vss-search-archive`](../../../../../skills/vss-search-archive/SKILL.md) |

**Easy to confuse:**

- `incident-start` (laptop, daily launch) vs. `incident-operate-vm` (the backend on `kwanz-ws`: native services, Compose, env). `start.sh --mode vm` self-heals the VM, so reach for `incident-operate-vm` only when that fails or you need to change something.
- `incident-analyze-video` (produce one report and check it) vs. `incident-run-eval` (batch-score many predictions against ground truth).
- `incident-manage-database` (schema, migrations, storage layout) vs. `incident-analyze-video` (rows written by one analysis).
- These skills vs. NVIDIA's `vss-deploy-profile`: that skill drives `dev-profile.sh`, which does **not** know the `incident` profile. Never use it to deploy or tear down this profile.

---

## Catalogue

| Skill | Description |
|---|---|
| [incident-start](incident-start/SKILL.md) | Prepare `.env.local` and symlinks, then launch via `start.sh --mode local\|vm`. Covers mode choice, SSH preflight, and health checks. |
| [incident-operate-vm](incident-operate-vm/SKILL.md) | Operate `kwanz-ws`: the native-vs-Docker split, `native-services.sh`, Compose appliances, `generated.env.remote` rules, the agent editable reinstall, and the troubleshooting order. Includes the never-run list. |
| [incident-analyze-video](incident-analyze-video/SKILL.md) | Upload → analyse → persist → review flow in both modes. Covers agent and console API contracts, error codes, where each row comes from, and verification. |
| [incident-manage-database](incident-manage-database/SKILL.md) | Supabase schema and `insert_incident` RPC, `supabase db push` with dry-run first, PostgREST vs direct-Postgres access, and the R2 key layout. |
| [incident-run-eval](incident-run-eval/SKILL.md) | Standalone `eval/` pipeline: embedding server, GT ingest, seeded split, batch run, aggregation, and hermetic tests. |

---

## Install

Claude Code needs no install step. [`/.claude/skills/`](../../../../../.claude/skills/) at the repo root holds symlinks to each skill folder here, so sessions started in this repo load them automatically.

For other hosts (Codex, Cursor, any agentskills.io host), use NVIDIA's install prompt with this directory: symlink each `skills/incident-*/` folder into the host's skills directory.

## Maintaining these skills

- **Source of truth.** This directory is canonical. Add a skill here, then add a matching symlink under the repo-root `.claude/skills/`: `ln -s ../../deploy/docker/developer-profiles/dev-profile-incident/skills/<name> .claude/skills/<name>`.
- **Frontmatter.** `name` must match the folder. `description` says when to use the skill and when not to. Keep `license` and `metadata`.
- **No duplicated facts.** Put facts in `.docs/` and link to them. A skill owns only the procedure: steps, commands, gates and verification.
- **Same PR.** When a command, port, script or contract changes, update the affected skill in the same PR as the `.docs/` update (see [`../AGENTS.md`](../AGENTS.md)).
- **No evals.** NVIDIA's Skills Eval CI only covers root `skills/**`, so these skills have none.
