<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# dev-profile-incident

Human-facing overview for the incident search and reporting profile.

## Documentation

- [Shared scope and architecture](.docs/incident-plan-implementation-shared.md)
- [Local LLM/VLM deployment](.docs/incident-plan-implementation-local.md)
- [Remote LLM/VLM deployment](.docs/incident-plan-implementation-remote.md)
- [Profile operations and status](.docs/incident-profile-operations.md)
- [Streamlit console](incident-console/README.md)
- [Next.js console](incident-console-v2/README.md)
- [Lifecycle scripts](.scripts/README.md)

# Steps to deploy

Secrets & environment files

1. Paste the `.env.local` under this directory
2. Run the command below under this directory as well

```bash
ln -s ../.env.local incident-console/.env.local
ln -s ../.env.local incident-console-v2/.env.local
ln -s ../.env.local vlm-gateway/.env.local
ln -s ../.env.local mock-backend/.env.local
```

3. Run `./start.sh --mode local` for the zero-GPU local v2 workflow, or `./start.sh --mode vm` to connect the laptop UI to the shared `kwanz-ws` backend.
