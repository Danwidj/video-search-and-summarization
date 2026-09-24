<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# dev-profile-incident

Human-facing overview for the incident search and reporting profile.

## Documentation

- [Action plan & scope](.docs/action-plan.md)
- [Current status & known issues](.docs/status.md)
- [System architecture & sequence flows](.docs/architecture.md)
- [Database schema & R2 storage](.docs/data.md)
- [Incident analysis schema & field mapping](.docs/analysis-schema.md)
- [Profile operations & runbook](.docs/incident-profile-operations.md)
- [Decision log](.docs/decisions.md)
- [Option B architecture restructure plan](.docs/restructure-plan.md)
- [Archive / Retired plans](.docs/archive/)
- [Streamlit console](incident-console/README.md)
- [Next.js console](incident-console-v2/README.md)
- [Lifecycle scripts](.scripts/README.md)

# Steps to set up and deploy

`./start.sh` is THE single command to set up and launch everything from your laptop.

### 1. Secrets & environment files

1. Place `.env.local` under this directory (`deploy/docker/developer-profiles/dev-profile-incident/.env.local`).
2. Symlink `.env.local` to the sub-services:

```bash
ln -sfn ../.env.local incident-console/.env.local
ln -sfn ../.env.local incident-console-v2/.env.local
ln -sfn ../.env.local vlm-gateway/.env.local
ln -sfn ../.env.local mock-backend/.env.local
```

### 2. Launching via start.sh (The Canonical Entry Point)

Run `start.sh` with your chosen mode:

- **Local Mode (Zero-GPU development):**
  ```bash
  ./start.sh --mode local
  ```
  Starts the local mock backend (`mock-backend/base_profile_mock` on `127.0.0.1:7777`), the local VLM gateway (`vlm-gateway` on `127.0.0.1:8600`), and launches `incident-console-v2` on port 3200 (never touches SSH).

- **VM Mode (Full blueprint stack on kwanz-ws):**
  ```bash
  ./start.sh --mode vm
  ```
  Connects to `kwanz-ws` over SSH (resolves your VM user from `Host kwanz-ws` in `~/.ssh/config` without prompting, preflighting SSH before startup), checks running services, automatically deploys or self-heals any missing Docker appliances and native services (`vss-agent`), opens the backgrounded SSH port tunnel (8000, 7777, 30081, 30082), and launches `incident-console-v2` on port 3200.
