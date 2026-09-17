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
  backend...); a not-yet-built `mock_data/` module is planned for a
  Postgres-schema mock of the console — see `mock-backend/README.md`.

## Deploy

This profile is deployed and torn down with the project's canonical scripts
(`dev-profile.sh`, `cleanup_all_datalog.sh`) - see the Overview doc's
copy-paste commands and the `mdx-*` shell aliases in
[`deploy/dotfiles/`](../../../dotfiles/README.md). Do not improvise raw
`docker`/`docker compose` invocations; the wrappers encode profile-specific
lifecycle steps.

## Current deployment on kwanz-ws

The profile's backend (`vss-agent`, LLM/VLM NIMs, VIOS) runs on the shared
`kwanz-ws` VM. **The `incident-console` UI runs on each team member's own
laptop, not on the VM** - an SSH tunnel connects the two. This supersedes an
earlier setup where the console ran as a shared container on the VM (see the
status table below).

### Connecting

1. SSH access to kwanz-ws under your own account (you should already have
   one - `yang`, `faith`, `claris`, `heng` each have their own checkout under
   `/home/`).
2. From your own laptop, run the `mdx-tunnel-incident` alias (from
   [`deploy/dotfiles/`](../../../dotfiles/README.md)) to forward the backend
   ports (agent 8000, NIMs 30081/30082, ingress 7777):
   ```bash
   mdx-tunnel-incident
   ```
   Leave it running in its own terminal - it's supposed to sit there silently
   (that's correct, not stuck). Quick health check from a second terminal:
   ```bash
   curl http://localhost:8000/health
   # should return: {"value":{"isAlive":true}}
   ```
3. Run the console locally against the tunneled backend, per
   [`incident-console/README.md`](incident-console/README.md)'s "Real backend
   on kwanz-ws via SSH tunnel (Phase 4)" section. Each person runs their own
   console instance against the shared backend, not a single shared UI.

### What's actually running

All of these are up under `/srv/rise-up/vss/deploy/docker`, started via:
```bash
cd /srv/rise-up/vss/deploy/docker
sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <service>
```
(the root `compose.yml` in `deploy/docker` is the one to use - **not** the one
inside `dev-profile-incident/`, which only defines the console app by itself)

| Container | Role | Status |
|---|---|---|
| `vss-agent` | AI agent — upload API, report generation | Up, healthy |
| `vss-incident-console` | the Streamlit UI | Up, but **superseded** — the console now runs on each person's own laptop instead (see "Connecting" above); this VM container is a leftover from the earlier shared-VM-console setup, not the path to use going forward |
| `vss-vios-streamprocessing` | video decode/encode core | Up, healthy |
| `vss-vios-nvstreamer` | upload ingestion | Up |
| `vss-vios-ingress` | nginx gateway for VST/storage API | Up, healthy |
| `vss-haproxy-ingress` | public-facing ingress on port 7777 | Up |
| `vss-vios-postgres` | VIOS's internal Postgres | Up, healthy |
| `redis` | cache | Up |
| `phoenix` | telemetry | Up |
| `vss-rtvi-embed` | embedding service | Up, healthy (search/MVP2-related, not required for MVP1 but running) |

**Not running / broken** (see "Known issues" below): `nvidia-cosmos3-reasoner`
(VLM — crash-looping), `nvidia-nemotron-nano-9b-v2` (LLM — never started),
`vss-vios-sensor` (sensor-ms — never started), `vss-broker-health-check`
(expected to fail, MVP2/Kafka-only).

### Live config notes (`generated.env.remote`)

The untracked live env file on the VM diverges from the tracked `.env`
template in a few places:

| Setting | Template value | Live value | Why |
|---|---|---|---|
| `VSS_APPS_DIR` | `/path/to/deploy/docker` (placeholder) | `/srv/rise-up/vss/deploy/docker` | Never filled in — broke every `include:` in the compose files |
| `VSS_DATA_DIR` | `/path/to/vss-apps-data` (placeholder) | `/srv/rise-up/vss-apps-data` | Same — needed for persistent volume mounts |
| `HOST_IP` | `<HOST_IP>` (placeholder) | `10.131.1.5` | The VM's own internal address |
| `EXTERNAL_IP` | derived from `HOST_IP` (wrong) | `localhost` | Must differ from `HOST_IP` — this is what gets embedded in URLs handed back to your browser/tunnel |
| `VSS_AGENT_CONFIG_FILE` | pointed at `dev-profile-search`'s config (zero report-gen capability) | `dev-profile-base`'s config | Search's config never had `report_agent`/`video_report_gen` wired in at all |
| `REPORT_REFERENCE_BASE_DIR` | unset (crashed startup) | `/tmp` | Agent's `eval` config schema required a valid string, even though eval isn't actually used here |
| `STREAM_PROCESSOR_HTTP_PORT` | unset → defaulted to `30001` | `10000` | nginx is hardcoded to proxy to `localhost:10000`, but the service's own default is `30001` — a pre-existing inconsistency in the repo's own shared `vst.env` |

### Known issues - not yet fixed, tracked as follow-up work

1. **`/analyze` won't go live even after an agent PR merges.** `vss-agent`
   deploys from NVIDIA's locked prebuilt image
   (`nvcr.io/nvidia/vss-core/vss-agent`) — there's no `build:` wiring anywhere
   to actually build the container from this repo's own code. Someone needs
   to add a `build:` context pointed at `services/agent/docker/Dockerfile`
   before agent-side code changes can ever run on the VM.
2. **The VLM (AI vision model) is crash-looping.** `VLM_DEVICE_ID='2'` in
   `generated.env.remote`, but this box only has GPUs `0` and `1`. Also
   `HARDWARE_PROFILE=H100` is wrong for this 2×A6000 box — should be `OTHER`.
   *(Coordinate with whoever last touched this config before changing it.)*
3. **`sensor-ms` container was never started.** Not blocking anything tested
   so far, but will break sensor management features if/when someone builds
   on them. Fix: `docker compose ... up -d sensor-ms`.
4. **The fix to `VSS_AGENT_CONFIG_FILE` only lives in the live untracked
   file**, not the tracked `.env` template in the repo
   (`dev-profile-incident/.env:246`) — anyone who regenerates their env from
   that template will silently reintroduce the original bug. Needs a real
   code fix.
5. **`INCIDENT_LLM_BASE_URL` points at a local mock server** that isn't
   running on the VM — currently harmless (nothing calls it yet), but will
   break the moment someone wires up the "direct LLM draft" fallback feature.
