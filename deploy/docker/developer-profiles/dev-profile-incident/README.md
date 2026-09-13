<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# dev-profile-incident

Developer profile for the incident search and reporting capstone (Daniel's
team, NVIDIA NVAITC-sponsored). It reuses NVIDIA's `bp_developer_search`
compose tag, so the deployed stack is a superset of everything the base +
search pipelines need, plus one profile-exclusive service: the
`incident-console` Streamlit app.

For the full plan - what ships when (MVP1/MVP2), deploy commands, GPU
topology, schema and API design - start at
[`docs/incident-plan/incident-plan-overview.md`](../../../../docs/incident-plan/incident-plan-overview.md).

## Layout

- [`compose.yml`](compose.yml) - profile entrypoint. Includes
  `./incident-console/compose.yml`; `BP_PROFILE` in `.env` is left unchanged
  (rides on the `search` compose tag, unlike the stock profiles that go
  through the `dev-profile` helper). No Kibana init block - this profile does
  not use Kibana.
- [`incident-console/`](incident-console/README.md) - the Streamlit console:
  Postgres-backed incident review UI. Database-backed only, no offline mode
  (`INCIDENT_DB_DSN` must be set). See its README for the local dev loop and
  [`db.py`](incident-console/db.py) (module docstring) for the authoritative
  schema.
- [`mock-backend/`](mock-backend/README.md) - zero-GPU mock backends for local
  UI development: `base_profile_mock/` (mocks the whole `bp_developer_base`
  backend so the real UI runs unmodified) plus a Postgres-schema mock area for
  the console.
- [`LOCAL_MOCK_LOOP.md`](LOCAL_MOCK_LOOP.md) - empirically verified
  native-only mock/frontend wiring (uv + npm, no Docker, no GPU, no SSH).

## Deploy

This profile is deployed and torn down with the project's canonical scripts
(`dev-profile.sh`, `cleanup_all_datalog.sh`) - see the Overview doc's
copy-paste commands and the `mdx-*` shell aliases in
[`deploy/dotfiles/`](../../../dotfiles/README.md). Do not improvise raw
`docker`/`docker compose` invocations; the wrappers encode profile-specific
lifecycle steps.
