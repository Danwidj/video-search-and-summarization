<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# archived

Retired components of the incident profile, kept for history and reference only.

Nothing here is launched by [`start.sh`](../start.sh), set up by `.githooks` (no `.env` files or `.env.local` symlinks are copied or created here), tested, or maintained. Do not build on it, import from it, or point it at the finals database. Active code lives one level up; see [`../AGENTS.md`](../AGENTS.md).

| Path | Was | Archived | Replacement |
|---|---|---|---|
| [`incident-console/`](incident-console/README.md) | Streamlit v1 console (retired 2026-09-24) | 2026-10-22 | [`incident-console-v2/`](../incident-console-v2/README.md) |
