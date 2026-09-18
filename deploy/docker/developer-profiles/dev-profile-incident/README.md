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
(`dev-profile.sh`, `cleanup_all_datalog.sh`) where they apply — note that
`dev-profile.sh` has **no `incident` profile** (only
`base|search|lvs|alerts`), so this profile's own backend deploy is the
direct compose invocation in the "What's actually running" section below
(see `docs/incident-plan/incident-plan-implementation-remote.md` §2). Do not
improvise raw `docker`/`docker compose` invocations.

### Lifecycle scripts (in this directory)

The old `mdx-*` shell aliases / `ngc-env-on` / `gpu` from
[`deploy/dotfiles/`](../../../dotfiles/README.md) moved here as standalone,
executable scripts — same behavior, ready to run individually:

| Script | Was | Runs on | What it does |
|---|---|---|---|
| `start.sh` | — (new) | **laptop** | One-command daily entry point: checks the VM backend deploy state over SSH, deploys fresh if nothing is running, **stops on a partial deploy**, opens the tunnel in the background, then runs the local console |
| `tunnel.sh` | `mdx-tunnel-incident` | **laptop** | Open the SSH tunnel to the kwanz-ws backend in the foreground (Ctrl-C closes it) |
| `tunnel-check.sh` | `mdx-tunnel-incident-check` | **laptop** | Prove the tunnel from the laptop end (agent health + NIM ports) |
| `status.sh` | `mdx-ps` | VM | `docker compose -p mdx ps` |
| `down.sh` | `mdx-down` | VM | Stop the stack **without `-v`** (preserves the ~35 GB model-weight cache — never run `dev-profile.sh down`) |
| `health.sh` | `mdx-health` | laptop/VM | Agent health probe on `:8000/health` |
| `logs.sh` | `mdx-logs` | VM | Tail one container's logs (default `vss-agent`) |
| `disk.sh` | `mdx-disk` | VM | `docker system df -v` |
| `rebuild-svc.sh` | `mdx-rebuild-svc` | VM | Fast single-service rebuild (`docker compose up -d --build --force-recreate <service>`) |
| `rebuild.sh` | `mdx-rebuild` | VM | Full stock-profile rebuild via `dev-profile.sh up` (interactive confirmation; wipes the model-weight cache) |
| `clean-datalog.sh` | `mdx-clean-datalog` | VM | Data-dir cleanup between deploys (requires passwordless sudo) |
| `ngc-env.sh` | `ngc-env-on` | VM | `source ./ngc-env.sh` to export the shared NGC credentials |
| `gpu.sh` | `gpu` | VM | One-shot `nvidia-smi` status |

Each script preserves the original alias/function's grounding comment and
safety behavior — check a script's header before using it.

## Current deployment on kwanz-ws

The profile's backend (`vss-agent`, LLM/VLM NIMs, VIOS) runs on the shared
`kwanz-ws` VM. **The `incident-console` UI runs on each team member's own
laptop, not on the VM** - an SSH tunnel connects the two. This supersedes an
earlier setup where the console ran as a shared container on the VM (see the
status table below).

### Connecting

#### One command (recommended)

From your own laptop, in this directory:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident
./start.sh
```

SSH access to kwanz-ws is per-person (see the manual flow below), so
`start.sh` no longer hardcodes a VM username: it prompts for one, pre-filled
with your local `$USER` as the default (just hit Enter if that matches your
VM account, or type a different one). Set `VSS_SSH_USER` to skip the prompt
non-interactively (e.g. in a script), or `VSS_SSH_TARGET` (full `user@host`)
to override the login entirely, same as before. `tunnel.sh` resolves its VM
login the same way.

`start.sh` checks the VM's deploy state over SSH (`docker compose -p mdx ps`):

- **Nothing running** → deploys the backend fresh over SSH (the profile's own
  deploy path: `docker compose -f compose.yml --env-file
  developer-profiles/dev-profile-incident/generated.env.remote up -d`), then
  opens the tunnel, then starts the console.
- **Everything expected up** → skips the deploy, straight to tunnel + console.
- **Partial deploy** → stops and prints exactly what's up vs. what's
  missing/expected (with a nonzero exit), telling you to clear the partial
  state manually before re-running. It deliberately never auto-reconciles or
  force-redeploys over a partial state.

It then backgrounds the SSH tunnel (and closes it when the console exits) and
starts the local Streamlit console. Run it from the laptop only — it refuses
to run on `kwanz-ws` itself.

#### Manual flow (same pieces, individually)

1. SSH access to kwanz-ws under your own account (you should already have
   one - `yang`, `faith`, `claris`, `heng` each have their own checkout under
   `/home/`).
2. From your own laptop, run `./tunnel.sh` (replaces the old
   `mdx-tunnel-incident` alias) to forward the backend ports (agent 8000,
   NIMs 30081/30082, ingress 7777):
   ```bash
   ./tunnel.sh
   ```
   Leave it running in its own terminal - it's supposed to sit there silently
   (that's correct, not stuck). Quick health check from a second terminal:
   ```bash
   ./tunnel-check.sh
   # or, plain curl:
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

1. **`vss-agent` now builds from source, but the VM hasn't redeployed yet.**
   `deploy/docker/services/agent/compose.yml`'s `vss-agent` service now carries
   a `build:` context (`services/agent/docker/Dockerfile`, context `services/`)
   alongside its `image:` tag, so `docker compose up -d --build vss-agent`
   rebuilds the container from this repo's own code (e.g. the `/analyze` route)
   instead of NVIDIA's locked prebuilt image. A plain `up -d` — no `--build` —
   still reuses whatever image already exists locally. What's currently running
   on the VM is still the prebuilt image; run one `--build` deploy there before
   relying on any agent-side code change.
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
