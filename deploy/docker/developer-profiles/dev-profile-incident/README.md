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

Each script preserves the original alias/function's grounding comment and
safety behavior — check a script's header before using it.

## Current deployment on kwanz-ws

The profile's backend (`vss-agent`, LLM/VLM NIMs, VIOS) runs on the shared
`kwanz-ws` VM. **The `incident-console` UI runs on each team member's own
laptop, not on the VM** - an SSH tunnel connects the two. This supersedes an
earlier setup where the console ran as a shared container on the VM (see the
status table below).

## Native vs. Docker service split

Fast-iterating application services run as native processes directly on
`kwanz-ws`, not in Docker, so a code change is a ~2s process restart instead
of a container rebuild. Media/appliance infra stays in Docker.

| Runs natively (kwanz-ws)                          | Runs in Docker                                                                                                                          |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `vss-agent` (`nat serve`, port 8000)                 | `vss-vios-streamprocessing`, `vss-vios-nvstreamer`, `vss-vios-ingress`, `vss-haproxy-ingress`, `vss-vios-postgres`, `redis`, `phoenix`     |
| `video-analytics-api` (`node index.js`, port 8081, optional — `ENABLE_ANALYTICS=true`) | `elasticsearch`, `kafka` (also gated by `ENABLE_ANALYTICS=true`)                                                     |
| `behavior-analytics` (`python3 apps/...`, port 8080, optional — `ENABLE_ANALYTICS=true`) |                                                                                                                        |

[`scripts/native-services.sh`](scripts/native-services.sh) is the VM-side
control script for the native half (`start`/`stop`/`restart`/`status`/`logs`,
each takes a space-separated service list, `all`, or `analytics` as
shorthand). It backgrounds each process with `nohup`, tracks it with a PID
file under `/srv/rise-up/vss/.run/<service>.pid`, redirects its stdout/stderr
to `/srv/rise-up/vss/.run/<service>.log`, and waits on a healthcheck loop
before reporting a service up (`vss-agent`'s `/health` endpoint; the
analytics services fall back to a port/log-line check). `start.sh`,
`scripts/status.sh`, `scripts/down.sh`, `scripts/logs.sh`, and
`scripts/rebuild-svc.sh` all delegate to it for the native half of their
respective jobs — see each script's header. Run it directly on the VM for
finer-grained control than `start.sh`'s all-or-nothing deploy, e.g.:

```bash
ssh kwanz-ws
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/scripts
./native-services.sh status
./native-services.sh restart vss-agent   # ~2s, no Docker rebuild
./native-services.sh logs vss-agent      # tails .run/vss-agent.log
```

### Pruning the now-unused Docker images

Once a service has been switched to native execution, its old Docker image
is dead weight on the VM's disk. `scripts/prune-native-images.sh` removes
the `vss-agent`, `vss-behavior-analytics`, and `vss-video-analytics-api`
images (plus any stopped containers still referencing them and dangling
leftovers) and prints disk usage before/after. It refuses to silently strand
you without an agent: if `services/agent/.venv/bin/nat` isn't present it
warns and asks for interactive confirmation before proceeding. Run it on the
VM after confirming the native services are up and healthy:

```bash
ssh kwanz-ws "bash /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/scripts/prune-native-images.sh"
```

## Laptop Setup: Secrets & Environment Files

The `incident-console` UI runs on each teammate's laptop, connecting either to the shared backend on `kwanz-ws` via an SSH tunnel (`./start.sh` or `./scripts/tunnel.sh`) or to a local mock backend (`./local-start.sh`).

**Secrets never go in tracked files.** The tracked `.env` files in git are placeholder templates only. On your laptop, real credentials live in untracked `.env.local` files that are ignored by git:

### Required & Optional Secret Files on Laptop

| Target File (Untracked) | Tracked Template to Copy | Required? | Used By |
|---|---|---|---|
| `deploy/docker/developer-profiles/dev-profile-incident/incident-console/.env.local` | [`incident-console/.env`](incident-console/.env) | **Required** | `incident-console` (Streamlit UI), `local-start.sh` (mock backend) |
| `deploy/docker/developer-profiles/dev-profile-incident/vlm-gateway/.env.local` | [`vlm-gateway/.env`](vlm-gateway/.env) | Optional | `vlm-gateway` (if running the hosted LLM/VLM inference proxy locally) |

> [!TIP]
> **Automatic Git Worktree Propagation:** If you use git worktrees, run `.githooks/activate.sh` once in your clone. The repo's [`.githooks/setup-worktree.sh`](../../../../.githooks/README.md) hook will automatically propagate untracked `.env` and `.env.local` files from the main worktree into newly created worktrees (copy-if-missing, never overwriting).

---

### Step-by-Step Setup for `incident-console/.env.local`

1. **Copy the tracked template:**
   ```bash
   cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
   cp .env .env.local
   ```

2. **Fill in the real values in `incident-console/.env.local`:**

   ```dotenv
   # =============================================================================
   # 1. DATABASE CONNECTION (Supabase Postgres via Session Pooler)
   # =============================================================================
   # Direct PostgreSQL connection string (SQLAlchemy sync URL) used by db.py.
   # Format: postgresql+psycopg2://<USER>:<PASSWORD>@<HOST>:5432/<DATABASE>?sslmode=require
   #
   # CRITICAL FORMAT NOTES:
   #  - Port: MUST use 5432 (session pooler mode) rather than 6543 (transaction pooler)
   #    so DDL, schema initialization, and session locks work properly.
   #  - URL Encoding: Percent-encode special characters in the password (e.g. "@" -> "%40",
   #    ":" -> "%3A", "#" -> "%23").
   #  - Purpose: Backs all incident review, edits, verification, notifications, and dashboard metrics.
   INCIDENT_DB_DSN=postgresql+psycopg2://postgres.[PROJECT-REF]:[PASSWORD]@[POOLER-HOST]:5432/postgres?sslmode=require

   # =============================================================================
   # 2. OBJECT STORAGE (Cloudflare R2 for Videos and Evidence)
   # =============================================================================
   # Cloudflare R2 credentials from the Cloudflare Dashboard (R2 -> Manage R2 API Tokens).
   # S3-compatible credentials with read/list permissions.
   #
   # Purpose: Used by r2_videos.py to generate presigned URLs for video playback in
   # Streamlit (st.video) and evidence images/screenshots for entities, instruments, and assets.
   R2_ACCOUNT_ID=<cloudflare-account-id-hex>
   R2_ACCESS_KEY=<s3-compatible-access-key-id>
   R2_SECRET_KEY=<s3-compatible-secret-access-key>
   R2_BUCKET=anomaly-detection-dataset

   # =============================================================================
   # 3. SUPABASE POSTGREST API (Agent & Mock-Backend Persistence)
   # =============================================================================
   # Supabase project URL and service role key (from Supabase Project Settings -> API).
   #
   # Purpose: Used by services/agent/src/vss_agents/utils/incident_db.py when testing
   # the agent or running the local mock backend (local-start.sh) for report generation persistence.
   # (Agent uses HTTPS PostgREST instead of port 5432 wire protocol due to VM network constraints).
   INCIDENT_SUPABASE_URL=https://[PROJECT-REF].supabase.co
   INCIDENT_SUPABASE_SERVICE_ROLE_KEY=<supabase-service-role-jwt>

   # =============================================================================
   # 4. BACKEND SERVICE & INFERENCE ENDPOINTS
   # =============================================================================
   # Base URL of vss-agent API (upload + AI analyze routes).
   # Under the SSH tunnel (scripts/tunnel.sh or start.sh), port 8000 forwards to the VM backend.
   INCIDENT_AGENT_BASE_URL=http://localhost:8000

   # OpenAI-compatible chat-completions endpoint for drafting & LLM judge:
   #  - Local mock server: http://localhost:8900/v1 (run mock_llm_server.py)
   #  - Real tunneled backend: http://localhost:30081/v1 (tunneled NIM on kwanz-ws)
   INCIDENT_LLM_BASE_URL=http://localhost:8900/v1

   # Embeddings endpoint for entity/instrument similarity matching (matching.py):
   # Unset defaults to no matching / mock server at http://localhost:8900/v1
   INCIDENT_EMBEDDING_BASE_URL=

   # Optional public video playback prefix; leave blank to use R2 presigned URLs.
   INCIDENT_VIDEO_BASE_URL=
   ```

3. **Verify configuration:**
   - Run unit tests to verify the local environment parses cleanly:
     ```bash
     uv run pytest
     ```
   - (Optional) Seed the database fixtures if starting fresh:
     ```bash
     uv run python scripts/seed_supabase.py  # 36 real video-backed incidents
     uv run python scripts/seed_mock8.py     # 8-video custom demo set
     ```

---

### Step-by-Step Setup for `vlm-gateway/.env.local` (Optional)

If you are developing or running the thin proxy for NVIDIA-hosted LLM/VLM inference locally:

1. **Copy the template:**
   ```bash
   cd deploy/docker/developer-profiles/dev-profile-incident/vlm-gateway
   cp .env .env.local
   ```

2. **Configure `.env.local`:**
   ```dotenv
   # Upstream NVIDIA-hosted inference endpoint (switchyard)
   VLM_GATEWAY_BASE_URL=https://switchyard-13doh4lsz.brevlab.com/v1

   # Upstream API key provided by the NVIDIA team
   VLM_GATEWAY_API_KEY=<upstream-api-key>

   # Local gateway listening port (default: 8600)
   VLM_GATEWAY_PORT=8600
   ```

3. **Run the gateway:**
   ```bash
   uv run uvicorn app:app --port 8600
   ```

---

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
to override the login entirely, same as before. `scripts/tunnel.sh` resolves its VM
login the same way.

`start.sh` checks the VM's deploy state over SSH — Docker containers
(`docker compose -p mdx ps`) **and** native services
(`scripts/native-services.sh status`, see "Native vs. Docker service split"
below):

- **Nothing running** → deploys the backend fresh over SSH: Docker appliance
  containers only (`docker compose -f compose.yml --env-file
developer-profiles/dev-profile-incident/generated.env.remote up -d
<docker-services>`, no `vss-agent` in that list), then starts the native
  services (`native-services.sh start`), then opens the tunnel, then starts
  the console.
- **Everything expected up** → skips the deploy, straight to tunnel + console.
- **Partial deploy** → stops and prints exactly what's up vs. what's
  missing/expected for both Docker and native services (with a nonzero exit),
  telling you to clear the partial state manually before re-running. It
  deliberately never auto-reconciles or force-redeploys over a partial state.

Set `ENABLE_ANALYTICS=true` to also bring up `video-analytics-api` and
`behavior-analytics` natively (plus `elasticsearch`/`kafka` in Docker).

##### Troubleshooting the VM SSH username

- **No prompt appears at all** — a `VSS_SSH_TARGET` env var is already set in
  your shell (it takes priority over the prompt). `unset VSS_SSH_TARGET` to
  be prompted again.
- **The pre-filled default is your local machine username, not necessarily
  your VM account** — kwanz-ws access is per-person and Tailscale-gated;
  don't just accept the default if you know it's wrong for you.
- **To check if a username is valid before running the whole script:**
  `ssh <username>@kwanz-ws echo ok`. A
  `tailscale: tailnet policy does not permit you to SSH as user "..."` error
  means that username isn't authorized for your device — try a different one
  or ask whoever manages VM access.
- **SSH works but `start.sh` still fails with a Docker permission error** — a
  `permission denied ... Docker daemon socket` error means that VM account
  needs Docker group access: on the VM, run `sudo usermod -aG docker
<username>` once (needs sudo there), then fully log out and reconnect
  (exit the SSH session and ssh back in) — group membership doesn't apply to
  an already-open session.

It then backgrounds the SSH tunnel (and closes it when the console exits) and
starts the local Streamlit console. Run it from the laptop only — it refuses
to run on `kwanz-ws` itself.

#### Manual flow (same pieces, individually)

1. SSH access to kwanz-ws under your own account (you should already have
   one - `yang`, `faith`, `claris`, `heng` each have their own checkout under
   `/home/`).
2. From your own laptop, run `./scripts/tunnel.sh` (replaces the old
   `mdx-tunnel-incident` alias) to forward the backend ports (agent 8000,
   NIMs 30081/30082, ingress 7777):
   ```bash
   ./scripts/tunnel.sh
   ```
   Leave it running in its own terminal - it's supposed to sit there silently
   (that's correct, not stuck). Quick health check from a second terminal:
   ```bash
   ./scripts/tunnel-check.sh
   # or, plain curl:
   curl http://localhost:8000/health
   # should return: {"value":{"isAlive":true}}
   ```
3. Run the console locally against the tunneled backend, per
   [`incident-console/README.md`](incident-console/README.md)'s "Real backend
   on kwanz-ws via SSH tunnel (Phase 4)" section. Each person runs their own
   console instance against the shared backend, not a single shared UI.

### What's actually running

Docker appliance containers are up under `/srv/rise-up/vss/deploy/docker`,
started via:

```bash
cd /srv/rise-up/vss/deploy/docker
sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <service>
```

(the root `compose.yml` in `deploy/docker` is the one to use - **not** the one
inside `dev-profile-incident/`, which only defines the console app by itself)

`vss-agent` itself is **not** one of these containers — it runs natively via
`scripts/native-services.sh` (see "Native vs. Docker service split" above).

| Service / Container         | Role                                      | Status                                                                                                                                                                                                                    |
| ---------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vss-agent` (native)         | AI agent — upload API, report generation | Up, healthy (`native-services.sh status`, not `docker compose ps`)                                                                                                                                                       |
| `vss-incident-console`      | the Streamlit UI                         | Up, but **superseded** — the console now runs on each person's own laptop instead (see "Connecting" above); this VM container is a leftover from the earlier shared-VM-console setup, not the path to use going forward |
| `vss-vios-streamprocessing` | video decode/encode core                 | Up, healthy                                                                                                                                                                                                             |
| `vss-vios-nvstreamer`       | upload ingestion                         | Up                                                                                                                                                                                                                      |
| `vss-vios-ingress`          | nginx gateway for VST/storage API        | Up, healthy                                                                                                                                                                                                             |
| `vss-haproxy-ingress`       | public-facing ingress on port 7777       | Up                                                                                                                                                                                                                      |
| `vss-vios-postgres`         | VIOS's internal Postgres                 | Up, healthy                                                                                                                                                                                                             |
| `redis`                     | cache                                    | Up                                                                                                                                                                                                                      |
| `phoenix`                   | telemetry                                | Up                                                                                                                                                                                                                      |
| `vss-rtvi-embed`            | embedding service                        | Up, healthy (search/MVP2-related, not required for MVP1 but running)                                                                                                                                                    |

**Not running / broken** (see "Known issues" below): `nvidia-cosmos3-reasoner`
(VLM — crash-looping), `nvidia-nemotron-nano-9b-v2` (LLM — never started),
`vss-vios-sensor` (sensor-ms — never started), `vss-broker-health-check`
(expected to fail, MVP2/Kafka-only).

### Live config notes (`generated.env.remote`)

The untracked live env file on the VM diverges from the tracked `.env`
template in a few places:

| Setting                      | Template value                                                        | Live value                       | Why                                                                                                                                                          |
| ---------------------------- | --------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `VSS_APPS_DIR`               | `/path/to/deploy/docker` (placeholder)                                | `/srv/rise-up/vss/deploy/docker` | Never filled in — broke every `include:` in the compose files                                                                                                |
| `VSS_DATA_DIR`               | `/path/to/vss-apps-data` (placeholder)                                | `/srv/rise-up/vss-apps-data`     | Same — needed for persistent volume mounts                                                                                                                   |
| `HOST_IP`                    | `<HOST_IP>` (placeholder)                                             | `10.131.1.5`                     | The VM's own internal address                                                                                                                                |
| `EXTERNAL_IP`                | derived from `HOST_IP` (wrong)                                        | `localhost`                      | Must differ from `HOST_IP` — this is what gets embedded in URLs handed back to your browser/tunnel                                                           |
| `VSS_AGENT_CONFIG_FILE`      | pointed at `dev-profile-search`'s config (zero report-gen capability) | `dev-profile-base`'s config      | Search's config never had `report_agent`/`video_report_gen` wired in at all                                                                                  |
| `REPORT_REFERENCE_BASE_DIR`  | unset (crashed startup)                                               | `/tmp`                           | Agent's `eval` config schema required a valid string, even though eval isn't actually used here                                                              |
| `STREAM_PROCESSOR_HTTP_PORT` | unset → defaulted to `30001`                                          | `10000`                          | nginx is hardcoded to proxy to `localhost:10000`, but the service's own default is `30001` — a pre-existing inconsistency in the repo's own shared `vst.env` |

### Known issues - not yet fixed, tracked as follow-up work

1. ~~**`vss-agent` now builds from source, but the VM hasn't redeployed yet.**
   `deploy/docker/services/agent/compose.yml`'s `vss-agent` service now carries
   a `build:` context (`services/agent/docker/Dockerfile`, context `services/`)
   alongside its `image:` tag, so `docker compose up -d --build vss-agent`
   rebuilds the container from this repo's own code (e.g. the `/analyze` route)
   instead of NVIDIA's locked prebuilt image. A plain `up -d` — no `--build` —
   still reuses whatever image already exists locally. What's currently running
   on the VM is still the prebuilt image; run one `--build` deploy there before
   relying on any agent-side code change.~~ **FIXED** — `start.sh` now passes `--build` on fresh deploys (see PR adding `--build` to the deploy command).
2. **The VLM (AI vision model) is crash-looping.** `VLM_DEVICE_ID='2'` in
   `generated.env.remote`, but this box only has GPUs `0` and `1`. Also
   `HARDWARE_PROFILE=H100` is wrong for this 2×A6000 box — should be `OTHER`.
   _(Coordinate with whoever last touched this config before changing it.)_
3. **`sensor-ms` container was never started.** Not blocking anything tested
   so far, but will break sensor management features if/when someone builds
   on them. Fix: `docker compose ... up -d sensor-ms`.
4. **Resolved (PR #59):** `VSS_AGENT_CONFIG_FILE` now points to the
   `dev-profile-base` config in the tracked `.env` template
   (`dev-profile-incident/.env:270`). The earlier bug (pointing at
   `dev-profile-search`) is fixed in the repo.
5. **`INCIDENT_LLM_BASE_URL` points at a local mock server** that isn't
   running on the VM — currently harmless (nothing calls it yet), but will
   break the moment someone wires up the "direct LLM draft" fallback feature.
