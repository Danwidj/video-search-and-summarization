<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->
<!--
agents:
  read-when: Orienting in the incident profile; adding, moving or renaming a doc or skill.
  owns: the documentation index and the first-time setup steps.
  rules: Update the index below in the same change as any doc or skill you add, move or rename.
-->

# Incident profile

Incident search and reporting on NVIDIA's VSS blueprint. A reviewer uploads a clip, a vision-language model writes a structured incident report, and reviewers edit it, mark one version official and search the evidence. Coding agents start at [AGENTS.md](AGENTS.md).

## Run it

1. Put your `.env.local` in this folder.
2. Link it into the sub-services:

   ```bash
   ln -sfn ../.env.local incident-console-v2/.env.local
   ln -sfn ../.env.local vlm-gateway/.env.local
   ln -sfn ../.env.local mock-backend/.env.local
   ```

3. Start everything from your laptop: `./start.sh --mode vm` (kwanz-ws over an SSH tunnel, GPU 0 only).

`./start.sh --mode vm --prod` runs the console as a production build (`next build`, then `next start`) instead of `next dev`; see the operations doc.

`./start.sh --mode mock` runs a zero-GPU mock instead. It is a mock of the backend, a backup that mimics it; verify UI and backend work on the VM, not against the mock. Modes, checks and troubleshooting: [incident-start skill](skills/incident-start/SKILL.md).

## What is inside

| Folder | What it is |
|---|---|
| [incident-console-v2](incident-console-v2/README.md) | The Next.js console |
| [vlm-gateway](vlm-gateway/README.md) | Key-holding proxy for the mock flow |
| [mock-backend](mock-backend/README.md) | Two zero-GPU mocks that mimic the backend |
| [contracts](contracts/README.md) | The incident contract: prompt, schema, goldens |
| [supabase](supabase/README.md) | Database schema and SQL harness; the [midterm record](supabase/midterm/README.md) is frozen |
| [eval](eval/README.md) | The P1/RP1 benchmark |
| [skills](skills/README.md) | Agent skills for operating the profile |
| [.scripts](.scripts/README.md), [.dotfiles](.dotfiles/README.md) | Lifecycle scripts; optional VM shell setup |
| [archived](archived/README.md) | Retired code, read-only |

## Read more

- [Status](.docs/status.md): what runs today, known issues, open actions
- [Action plan](.docs/action-plan.md): goals and scope
- [Architecture](.docs/architecture.md): context, containers, runtime and deployment
- [Console reference](.docs/console-reference.md): pages, routes and configuration
- [Data layer](.docs/data.md): tables, functions, security, R2 keys
- [Analysis schema](.docs/analysis-schema.md): report fields, prompts, validation
- [Operations runbook](.docs/incident-profile-operations.md): running kwanz-ws
- [VM API contracts](.docs/vm-api-contracts.md): agent endpoints and the tunnel
- [Decision log](.docs/decisions.md): why things are the way they are; [superseded entries](.docs/archive/decisions-superseded.md) are archived
- [Search spec](.docs/mvp2/README.md), [console layout](.docs/mvp2/console-hexagonal-architecture.md), [report-first chat routing](.docs/mvp2/chat-routing.md), [search evaluation](.docs/mvp2/eval.md), [experiment decisions](.docs/mvp2/experiment-decision-record.md)
- Evaluation reports: [final report](eval/docs/experiments/final-report.md), [methodology v2.0](eval/methodology/evaluation-methodology-v2.0.md), [all experiment reports](eval/docs/experiments/)
