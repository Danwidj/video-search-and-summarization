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
- [Archive / Retired plans](.docs/archive/)
- [Streamlit console](incident-console/README.md)
- [Next.js console](incident-console-v2/README.md)
- [Lifecycle scripts](.scripts/README.md)

# Steps to deploy

Secrets & environment files

1. Paste the `.env.local` under this directory.
2. Run the command below from this directory as well. The `-f` flag makes
   rerunning the setup safe if a symlink already exists.

```bash
ln -sfn ../.env.local incident-console/.env.local
ln -sfn ../.env.local incident-console-v2/.env.local
ln -sfn ../.env.local vlm-gateway/.env.local
ln -sfn ../.env.local mock-backend/.env.local
```

3. Run `./start.sh --mode local` for the zero-GPU local v2 workflow, or `./start.sh --mode vm` to connect the laptop UI to the shared `kwanz-ws` backend.
