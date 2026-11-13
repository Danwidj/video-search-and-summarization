<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# archived

Retired components of the incident profile, kept for history and reference only.

Nothing here is launched by [`start.sh`](../start.sh), set up by `.githooks` (no `.env` files or `.env.local` symlinks are copied or created here), tested, or maintained. Do not build on it, import from it, or point it at the finals database. Active code lives one level up; see [`../AGENTS.md`](../AGENTS.md).

| Path | Was | Archived | Replacement |
|---|---|---|---|
| [`supabase/midterm/`](supabase/midterm/README.md) | Frozen midterm database record: 14 migrations, base tables, freeze and unfreeze SQL | 2026-11-11 | [`supabase/migrations/`](../supabase/migrations/) |
| [`supabase/copy/`](supabase/copy/) | One-way midterm to finals data copy | 2026-11-11 | None (done once) |
| [`supabase/r2/`](supabase/r2/) | One-off R2 rename script | 2026-11-11 | None (done once) |

The midterm harness (`test_freeze.py`, `rehearse.py`, `parity_check.py`) lives in [`supabase/tests/`](supabase/tests/) and reads these archived files.
