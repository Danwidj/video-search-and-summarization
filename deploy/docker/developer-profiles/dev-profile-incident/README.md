<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# dev-profile-incident

Human-facing overview for the incident search and reporting profile. Coding agents start at [`AGENTS.md`](AGENTS.md).

## Documentation

**For agents**
- [AGENTS.md](AGENTS.md): components, checks, architecture rules, boundaries, docs rule
- [Skills router](skills/README.md): operational skills (`incident-start`, `incident-operate-vm`, `incident-analyze-video`, `incident-search`, `incident-manage-database`, `incident-run-eval`)

**Reference (`.docs/`)**
- [Current status & known issues](.docs/status.md)
- [Action plan & scope](.docs/action-plan.md)
- [System architecture & sequence flows](.docs/architecture.md)
- [Database schema & R2 storage](.docs/data.md)
- [Incident analysis schema & field mapping](.docs/analysis-schema.md)
- [Profile operations & runbook](.docs/incident-profile-operations.md)
- [VM API contracts & tunnel endpoints (frontend)](.docs/vm-api-contracts.md)
- [Decision log](.docs/decisions.md)
- [MVP2 natural-language search overview](.docs/mvp2/README.md)
- [MVP2 evaluation plan (retrieval, critic, detector, embeddings)](.docs/mvp2/eval.md)
- [Ground-truth refinement and prompt-experiment plan (direct VLM vs VSS)](.docs/mvp2/ground-truth-and-prompt-experiments-plan.md)
- [Annotation guidelines v1.0 (approved)](eval/ground_truth/annotation-guidelines-v1.0.md)
- [incident-console-v2 hexagonal layout](.docs/mvp2/console-hexagonal-architecture.md)

**Components**
- [Next.js console (v2, active)](incident-console-v2/README.md)
- [VLM gateway](vlm-gateway/README.md)
- [Mock backends](mock-backend/README.md)
- [Evaluation pipeline](eval/README.md)
- [Incident contract (prompt + schema)](contracts/README.md)
- [Experiment prompt registry (not the production contract)](contracts/experiments/README.md)
- [Prompt experiment runner and guards](eval/experiments/README.md)
- [Supabase schema, SQL harness and midterm-to-finals copy](supabase/README.md); [frozen midterm record](supabase/midterm/README.md)
- [Lifecycle scripts](.scripts/README.md)
- [VM dotfiles](.dotfiles/README.md)
- [Archived components](archived/README.md) (read-only)

## Steps to set up and deploy

Full procedure, checks and troubleshooting: [`incident-start`](skills/incident-start/SKILL.md).

`./start.sh` is THE single command to set up and launch everything from your laptop.

### 1. Secrets & environment files

1. Place `.env.local` under this directory (`deploy/docker/developer-profiles/dev-profile-incident/.env.local`).
2. Symlink `.env.local` to the sub-services:

```bash
ln -sfn ../.env.local incident-console-v2/.env.local
ln -sfn ../.env.local vlm-gateway/.env.local
ln -sfn ../.env.local mock-backend/.env.local
```

### 2. Launching via start.sh (The Canonical Entry Point)

Run `start.sh` with your chosen mode:

```bash
./start.sh --mode mock   # zero GPU: local mock backend and VLM gateway, no SSH
./start.sh --mode vm     # kwanz-ws over an SSH tunnel (VSS uses GPU 0 only there)
```

What each mode starts and how to troubleshoot it: [`incident-start`](skills/incident-start/SKILL.md).
