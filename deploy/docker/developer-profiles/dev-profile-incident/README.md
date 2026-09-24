<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# dev-profile-incident

Developer profile for the incident search and reporting capstone (Daniel's
team, NVIDIA NVAITC-sponsored). A video-driven incident search and reporting
system built on this VSS blueprint fork. Two console frontends exist:

- **`incident-console` (v1)** — Streamlit app, Postgres-backed incident review UI. Runs on each team member's laptop, connecting to the shared backend on `kwanz-ws` via SSH tunnel (or to a local mock backend).
- **`incident-console-v2`** — Next.js App Router frontend for video upload, VLM analysis, incident reporting, review, and evaluation. Uses existing HTTP contracts (mock/real `vss-agent`, VLM gateway, Supabase/PostgREST, Cloudflare R2) without copying the v1 interface. Runs on each team member's laptop on port 3200.

It reuses NVIDIA's `bp_developer_search` compose tag, so the deployed stack is a
superset of everything the base + search pipelines need. The profile-exclusive
services are the two console apps (the v1 Streamlit container on the VM is a
leftover from an earlier shared-UI setup and is no longer the intended path).

For technical reference docs (GPU topology, local vs. remote LLM/VLM deployment,
detailed Postgres schema specs, and eval methodology), see the companion files in
[`.docs/`](.docs/):
- [`incident-plan-implementation-local.md`](.docs/incident-plan-implementation-local.md) — Local NIM container deployment mode, GPU topology, profile setup.
- [`incident-plan-implementation-remote.md`](.docs/incident-plan-implementation-remote.md) — Remote NGC-hosted LLM/VLM deployment mode.
- [`incident-plan-implementation-shared.md`](.docs/incident-plan-implementation-shared.md) — Mode-independent technical specs: Postgres schema, Cloudflare R2, UI/API specs, eval methodology.

---

## 1. Scope & Architecture Decisions

### Scope breakdown

- **MVP1 (no natural-language search):**
  - Video catalog, upload, metadata editing, retention.
  - Report generation with structured fields (description, persons, classification, severity, confidence, start/end timestamps).
  - One-click pipeline trigger, status transitions, high-severity notifications.
  - Console UI except the search box; human-eval flow + report-quality scoring.

- **MVP2 (adds):**
  - Natural-language search (RT-CV + RT-Embed + Elasticsearch stack; `search_agent`/`embed_search` wired into `config.yml`).
  - Retrieval precision/recall/F1 evaluation.

### Standing facts & design decisions

- **Profile tag:** Reuses the `bp_developer_search` compose tag; `BP_PROFILE` in `.env` is left unchanged.
- **Agent configuration:** `config.yml` starts from base's `report_agent`/`video_report_gen` and appends search functions at MVP2.
- **Pipeline orchestration:** Extends `vss-agent` tool-calling (`POST /api/v1/incidents/{id}/analyze`).
- **Storage architecture:** Cloudflare R2 is the canonical, permanent video store; Postgres (Supabase) is the canonical report store; local VIOS disk acts as a working cache.
- **User model:** `edited_by`, `verified_by`, and `rater` are freeform text fields (who typed their name), not foreign keys to a user table — no accounts required.
- **Authoritative schema:** [`incident-console/db.py`](incident-console/db.py) (module docstring + [`incident-console/README.md`](incident-console/README.md)) defines the 12-table-plus-matches schema supporting multiple model runs over the same video plus a parallel human ground-truth set. The console is database-backed only; there is no offline CSV-preview UI mode.
- **Agent database access:** `services/agent/src/vss_agents/utils/incident_db.py` communicates via HTTPS PostgREST (`supabase-py`), not raw Postgres wire protocol on port 5432 (which is blocked by the VM's network environment).
- **Git remotes:** `origin` is the team fork; `upstream` is NVIDIA's repository.

---

## 2. Layout

- [`compose.yml`](compose.yml) — Profile entrypoint. Includes `./incident-console/compose.yml` and `./vlm-gateway/compose.yml`. No Kibana init block (this profile does not use Kibana).
- [`.env`](.env) — Tracked placeholder template for the profile (compose-level variables, `VLM_GATEWAY_*`). Real values never go here; see [Laptop Setup](#6-laptop-setup-secrets--environment-files).
- [`incident-console/`](incident-console/README.md) — The Streamlit console (v1): Postgres-backed incident review UI (`INCIDENT_DB_DSN` required), plus the Tier 1 GT evaluation and the P1 multi-model VLM evaluation scripts. See its README for the local dev loop and [`db.py`](incident-console/db.py) for the authoritative schema.
- [`incident-console-v2/`](incident-console-v2/README.md) — Next.js App Router frontend (v2): video upload, VLM analysis, incident reporting, review, dashboard, and ground-truth evaluation. Server-only config via `VLM_GATEWAY_URL`, `VLM_MODEL`, `INCIDENT_AGENT_BASE_URL`, `INCIDENT_SUPABASE_URL`/`INCIDENT_SUPABASE_SERVICE_ROLE_KEY`, `R2_*`. See its README for the local dev loop (mock backend on 7777, VLM gateway on 8600, Next.js on 3200).
- [`vlm-gateway/`](vlm-gateway/README.md) — Thin FastAPI proxy (port 8600) that holds the upstream NVIDIA-hosted inference key (`VLM_GATEWAY_API_KEY`) server-side; v2 calls it for video analysis.
- [`mock-backend/`](mock-backend/README.md) — Zero-GPU mock backends for local UI development: [`base_profile_mock/`](mock-backend/base_profile_mock/README.md) mocks the whole `bp_developer_base` backend (vss-agent API + VIOS/VST + LLM/VLM inference, port 7777; used by both consoles); [`search_profile_mock/`](mock-backend/search_profile_mock/README.md) is its `bp_developer_search` superset (port 7778).
- [`.docs/`](.docs/) — Technical reference docs (`incident-plan-implementation-local.md`, `-remote.md`, `-shared.md`).
- [`.scripts/`](.scripts/README.md) — Standalone deployment and operational scripts (`status.sh`, `down.sh`, `health.sh`, `tunnel.sh`, `native-services.sh`, etc.).
- [`.dotfiles/`](.dotfiles/README.md) — Personal, opt-in shell QoL bootstrap for `kwanz-ws` accounts.
- [`start.sh`](start.sh) & [`local-start.sh`](local-start.sh) — Laptop-side entrypoint scripts (for v1 Streamlit console).

---

## 3. Environments and Access

- **Hardware (`kwanz-ws` VM):** 2× RTX A6000 (48 GB each), AMD Threadripper PRO 5975WX, 251 GiB RAM, 1.8 TB NVMe.
- **Tailscale:** `kwanz-ws.tailf3aa43.ts.net`.
- **VM checkout:** `/srv/rise-up/vss`.
- **NGC credentials on VM:** `/srv/rise-up/.ngc_env` (`set -a; source /srv/rise-up/.ngc_env; set +a` or `source .scripts/ngc-env.sh`).
- **Direct UI tunnel (base profile):** `ssh -N -L 7777:10.131.1.5:7777 <user>@kwanz-ws`, browse `http://localhost:7777`.
- **Deploy flags used on this host:** `--host-ip 10.131.1.5 --external-ip localhost --hardware-profile OTHER`.

---

## 4. Deploy & Operation

### Deployment principles

This profile is deployed and torn down with the project's canonical scripts
(`dev-profile.sh`, `cleanup_all_datalog.sh`) where they apply. Note that
**`dev-profile.sh` has no `incident` profile** (only `base|search|lvs|alerts`).

For `dev-profile-incident`:
- The backend deploys via direct docker compose invocation (`docker compose --env-file generated.env.<local|remote> up -d`) plus native services (see [Live deployment on kwanz-ws](#82-live-deployment-on-kwanz-ws) and [Native vs. Docker service split](#5-native-vs-docker-service-split)).
- **Never run `dev-profile.sh down`** on `kwanz-ws` — that script tears down the stack with `-v` and wipes the data directory, destroying ~35 GB of cached model weights. Use `./.scripts/down.sh` or plain `docker compose down`.
- Local UI iteration needs no GPU/VM:
  ```bash
  cd deploy/docker/developer-profiles/dev-profile-incident/incident-console
  uv sync
  uv run streamlit run app.py
  ```
  (See [`incident-console/README.md`](incident-console/README.md) for the full local dev loop).

Each script under [`.scripts/`](.scripts/README.md) preserves the original alias/function's
grounding comment and safety behavior — check a script's header before using it.

### Reference: Running NVIDIA stock profiles

For testing baseline NVIDIA blueprint behavior directly on `kwanz-ws`:

#### Stock `base`, local LLM/VLM
Verified working; tuning lives in each model's `deploy/docker/services/nim/<model>/hw-OTHER.env`, no override flags needed:

```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a
./deploy/docker/scripts/dev-profile.sh up --profile base --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 --llm-device-id 0 \
  --vlm nvidia/cosmos3-reasoner --vlm-device-id 1
```

#### Stock `base`, remote LLM/VLM
Verified working; uses `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` for both roles:

```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a
export LLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export VLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export OPENAI_API_KEY="$NVIDIA_API_KEY"
./deploy/docker/scripts/dev-profile.sh up --profile base --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --use-remote-llm --llm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning --llm-model-type openai \
  --use-remote-vlm --vlm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning --vlm-model-type openai
```

- `--llm-model-type`/`--vlm-model-type` must be `openai`, not `nim`. `nim`-type is non-functional (upstream `nvidia-nat` bug: `nim_langchain` leaks `verify_ssl` into the request body; issue #1894 / PR #1862).

---

## 5. Native vs. Docker Service Split

Fast-iterating application services run as native processes directly on
`kwanz-ws`, not in Docker, so a code change is a ~2s process restart instead
of a container rebuild. Media/appliance infra stays in Docker.

| Runs natively (kwanz-ws)                          | Runs in Docker                                                                                                                          |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `vss-agent` (`nat serve`, port 8000)                 | `vss-vios-streamprocessing`, `vss-vios-nvstreamer`, `vss-vios-ingress`, `vss-haproxy-ingress`, `vss-vios-postgres`, `redis`, `phoenix`     |
| `video-analytics-api` (`node index.js`, port 8081, optional — `ENABLE_ANALYTICS=true`) | `elasticsearch`, `kafka` (also gated by `ENABLE_ANALYTICS=true`)                                                     |
| `behavior-analytics` (`python3 apps/...`, port 8080, optional — `ENABLE_ANALYTICS=true`) |                                                                                                                        |

[`.scripts/native-services.sh`](.scripts/native-services.sh) is the VM-side
control script for the native half (`start`/`stop`/`restart`/`status`/`logs`,
each takes a space-separated service list, `all`, or `analytics` as
shorthand). It backgrounds each process with `nohup`, tracks it with a PID
file under `/srv/rise-up/vss/.run/<service>.pid`, redirects its stdout/stderr
to `/srv/rise-up/vss/.run/<service>.log`, and waits on a healthcheck loop
before reporting a service up (`vss-agent`'s `/health` endpoint; the
analytics services fall back to a port/log-line check). `start.sh`,
`.scripts/status.sh`, `.scripts/down.sh`, `.scripts/logs.sh`, and
`.scripts/rebuild-svc.sh` all delegate to it for the native half of their
respective jobs — see each script's header. Run it directly on the VM for
finer-grained control than `start.sh`'s all-or-nothing deploy, e.g.:

```bash
ssh kwanz-ws
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts
./native-services.sh status
./native-services.sh restart vss-agent   # ~2s, no Docker rebuild
./native-services.sh logs vss-agent      # tails .run/vss-agent.log
```

### Pruning the now-unused Docker images

Once a service has been switched to native execution, its old Docker image
is dead weight on the VM's disk. `.scripts/prune-native-images.sh` removes
the `vss-agent`, `vss-behavior-analytics`, and `vss-video-analytics-api`
images (plus any stopped containers still referencing them and dangling
leftovers) and prints disk usage before/after. It refuses to silently strand
you without an agent: if `services/agent/.venv/bin/nat` isn't present it
warns and asks for interactive confirmation before proceeding. Run it on the
VM after confirming the native services are up and healthy:

```bash
ssh kwanz-ws "bash /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts/prune-native-images.sh"
```

---

## 6. Laptop Setup: Secrets & Environment Files

Both console frontends run on each teammate's laptop, connecting either to the shared backend on `kwanz-ws` via an SSH tunnel (`./start.sh` or `./.scripts/tunnel.sh`) or to a local mock backend (`./local-start.sh` for v1; `incident-console-v2/README.md` for v2).

**Secrets never go in tracked files.** The tracked `.env` files in git are placeholder templates only (`dev-profile-incident/.env` for the profile/compose and `VLM_GATEWAY_*` keys, `incident-console/.env` for the console's `INCIDENT_*` / `R2_*` keys). On your laptop, all local credentials are consolidated into a single untracked file at the profile root (`dev-profile-incident/.env.local`), and each sub-service points to it via a relative symlink (`.env.local -> ../.env.local`):

### Secret Files Layout on Laptop

| File | Type | Used By |
|---|---|---|
| `deploy/docker/developer-profiles/dev-profile-incident/.env.local` | Untracked root secrets file | All local services in this profile |
| `incident-console/.env.local` | Symlink (`../.env.local`) | `incident-console` (Streamlit UI v1), `local-start.sh` (mock backend) |
| `incident-console-v2/.env.local` | Symlink (`../.env.local`) | `incident-console-v2` (Next.js UI v2) |
| `vlm-gateway/.env.local` | Symlink (`../.env.local`) | `vlm-gateway` (hosted LLM/VLM inference proxy) |

> [!TIP]
> **Automatic Git Worktree Propagation:** If you use git worktrees, run `.githooks/activate.sh` once in your clone. The repo's [`.githooks/setup-worktree.sh`](../../../../.githooks/README.md) hook automatically propagates untracked `.env` and `.env.local` files as well as relative symlinks from the main worktree into newly created worktrees (copy-if-missing, never overwriting). In a fresh clone with no root `.env.local` it seeds one from the tracked `.env` template, and in every worktree it re-creates any of the three subfolder `.env.local` symlinks that is missing, a real file, or pointing elsewhere.

---

### Step-by-Step Setup for `dev-profile-incident/.env.local`

1. **Populate the shared secrets file:**
   Create or edit `deploy/docker/developer-profiles/dev-profile-incident/.env.local` with real values (the sub-service symlinks point to this file):

2. **Fill in the real values in `dev-profile-incident/.env.local`:**

   ```dotenv
   # =============================================================================
   # 1. DATABASE CONNECTION (Supabase Postgres)
   # =============================================================================
   # Direct PostgreSQL connection string (SQLAlchemy sync URL) used by db.py.
   # Format: postgresql+psycopg2://<USER>:<PASSWORD>@<HOST>:5432/<DATABASE>?sslmode=require
   #
   # CRITICAL FORMAT NOTES:
   #  - Port/endpoint: use the session pooler (5432), or the direct connection if your
   #    network has IPv6 - not the transaction pooler (6543). See incident-console/README.md
   #    "Database connection" for the documented reasons and measurements.
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
   # Under the SSH tunnel (.scripts/tunnel.sh or start.sh), port 8000 forwards to the VM backend.
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
   - Run unit tests (from `incident-console/`) to verify the local environment parses cleanly:
     ```bash
     cd incident-console
     uv run pytest
     ```
   - (Optional) Seed the database fixtures if starting fresh:
     ```bash
     uv run python scripts/seed_supabase.py  # 36 real video-backed incidents
     uv run python scripts/seed_mock8.py     # 8-video custom demo set
     ```

---

### Step-by-Step Setup for `incident-console-v2/.env.local` (v2 Next.js)

1. **Add the server-only configuration documented in [`incident-console-v2/README.md`](incident-console-v2/README.md#server-only-configuration) to the shared root file.**
   `incident-console-v2/.env.local` is a symlink to `../.env.local` (Next.js loads it automatically), so edit
   `deploy/docker/developer-profiles/dev-profile-incident/.env.local` — do **not** `cat >` or otherwise recreate
   `incident-console-v2/.env.local`, which would overwrite the whole shared file through the symlink. Keys already
   present for v1 (`INCIDENT_SUPABASE_*`, `R2_*`) are shared. The full set v2 reads:
   ```dotenv
   # VLM Gateway (holds upstream inference credential; NOT exposed to browser)
   VLM_GATEWAY_URL=http://127.0.0.1:8600
   VLM_MODEL=nvidia/cosmos-3-nano-reasoner

   # vss-agent (mock or real) for three-step video upload + follow-up chat
   INCIDENT_AGENT_BASE_URL=http://127.0.0.1:7777

   # Supabase PostgREST (report metadata persistence)
   INCIDENT_SUPABASE_URL=https://[PROJECT-REF].supabase.co
   INCIDENT_SUPABASE_SERVICE_ROLE_KEY=<supabase-service-role-jwt>

   # Cloudflare R2 (private video storage; signed URLs generated server-side)
   R2_ACCOUNT_ID=<cloudflare-account-id-hex>
   R2_ACCESS_KEY=<s3-compatible-access-key-id>
   R2_SECRET_KEY=<s3-compatible-secret-access-key>
   R2_BUCKET=anomaly-detection-dataset
   ```

   Note that v1 uses `INCIDENT_AGENT_BASE_URL=http://localhost:8000` (tunneled real agent) in the same file; for the
   v2 mock-backend loop set it to `http://127.0.0.1:7777` while you work on v2.

   > **Do not** prefix any of these with `NEXT_PUBLIC_` — they must remain server-only. `GET /api/health` returns only configuration and reachability booleans; it never returns URLs or credentials.

2. **Verify configuration:**
   - Start the three required local services (see [`incident-console-v2/README.md`](incident-console-v2/README.md#local-development)):
     1. Mock backend on port 7777
     2. VLM gateway on port 8600
     3. `npm run dev` (Next.js on port 3200)
   - Check `GET http://localhost:3200/api/health` — it should return `status: "ready"` (HTTP 200): agent, gateway and PostgREST report `configured: true` / `reachable: true`, and R2 reports `configured: true` (R2 has no reachability probe), before testing the upload-to-report workflow.

---

### Step-by-Step Setup for `vlm-gateway/.env.local` (Optional)

If you are developing or running the thin proxy for NVIDIA-hosted LLM/VLM inference locally:

1. **Verify symlink and configure credentials:**
   `vlm-gateway/.env.local` is a symlink pointing to `../.env.local`. Ensure `VLM_GATEWAY_API_KEY` is set in the shared `deploy/docker/developer-profiles/dev-profile-incident/.env.local`:

2. **Configuration in `dev-profile-incident/.env.local`:**
   ```dotenv
   # Upstream NVIDIA-hosted inference endpoint (switchyard)
   VLM_GATEWAY_BASE_URL=https://switchyard-13doh4lsz.brevlab.com/v1

   # Upstream API key provided by the NVIDIA team
   VLM_GATEWAY_API_KEY=<upstream-api-key>
   ```

   The listening port is set by uvicorn's `--port` (8600 below); `app.py` does not read `VLM_GATEWAY_PORT`.

3. **Run the gateway** (from `vlm-gateway/`). `app.py` does not load `.env.local` itself, so pass it to `uv`:
   ```bash
   uv run --env-file .env.local uvicorn app:app --port 8600
   ```

---

## 7. Connecting to the Shared Backend

The profile's backend (`vss-agent`, LLM/VLM NIMs, VIOS) runs on the shared
`kwanz-ws` VM. **Both console UIs run on each team member's own laptop, not
on the VM** — an SSH tunnel connects the laptop to the VM backend. This
supersedes an earlier setup where the v1 console ran as a shared container on
the VM (see [Live deployment on kwanz-ws](#82-live-deployment-on-kwanz-ws)).

- **`incident-console` (v1):** Uses `./start.sh` (one-command: checks VM deploy state, deploys if needed, opens tunnel, starts Streamlit) or manual `./.scripts/tunnel.sh` + Streamlit per its README.
- **`incident-console-v2` (v2):** Uses the same SSH tunnel (`./.scripts/tunnel.sh` forwards agent 8000, NIMs 30081/30082, ingress 7777). Configure `INCIDENT_AGENT_BASE_URL=http://localhost:8000` (tunneled) and `VLM_GATEWAY_URL=http://localhost:8600` (if running gateway locally) or the tunneled VLM NIM endpoint. The v2 frontend does not have a dedicated `start.sh` entrypoint; run the tunnel manually, then `npm run dev` in `incident-console-v2/`. The mock-backend workflow (no VM) is documented in `incident-console-v2/README.md`.

### One command (recommended)

From your own laptop, in this directory:

```bash
cd deploy/docker/developer-profiles/dev-profile-incident
./start.sh
```

SSH access to kwanz-ws is per-person (see the manual flow below), so
`start.sh` no longer hardcodes a VM username: it prompts for one, pre-filled
with the `User` from your `~/.ssh/config` entry for `kwanz-ws` if there is one,
else your local `$USER` (just hit Enter if that matches your VM account, or type
a different one; the prompt accepts the default after 5 s). Set `VSS_SSH_USER` to
skip the prompt non-interactively (e.g. in a script), `VSS_SSH_TARGET` (full
`user@host`) to override the login entirely, or `VSS_SSH_HOST` to target a
host other than `kwanz-ws`. `.scripts/tunnel.sh` resolves its VM
login the same way.

`start.sh` checks the VM's deploy state over SSH — Docker containers
(`docker compose -p mdx ps`) **and** native services
(`.scripts/native-services.sh status`, see [Native vs. Docker service split](#5-native-vs-docker-service-split)):

- **Nothing running** → deploys the backend fresh over SSH: Docker appliance
  containers only (`docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <docker-services>`, no `vss-agent` in that list), then starts the native
  services (`native-services.sh start`), then opens the tunnel, then starts
  the console.
- **Everything expected up** → skips the deploy, straight to tunnel + console.
- **Partial deploy** → stops and prints exactly what's up vs. what's
  missing/expected for both Docker and native services (with a nonzero exit),
  telling you to clear the partial state manually before re-running. It
  deliberately never auto-reconciles or force-redeploys over a partial state.

Set `ENABLE_ANALYTICS=true` to also bring up `video-analytics-api` and
`behavior-analytics` natively (plus `elasticsearch`/`kafka` in Docker).

#### Troubleshooting the VM SSH username

- **No prompt appears at all** — a `VSS_SSH_TARGET` env var is already set in
  your shell (it takes priority over the prompt). `unset VSS_SSH_TARGET` to
  be prompted again.
- **The pre-filled default is your ssh-config or local machine username, not
  necessarily your VM account** — kwanz-ws access is per-person and Tailscale-gated;
  don't just accept the default if you know it's wrong for you.
- **To check if a username is valid before running the whole script:**
  `ssh <username>@kwanz-ws echo ok`. A
  `tailscale: tailnet policy does not permit you to SSH as user "..."` error
  means that username isn't authorized for your device — try a different one
  or ask whoever manages VM access.
- **SSH works but `start.sh` still fails with a Docker permission error** — a
  `permission denied ... Docker daemon socket` error means that VM account
  needs Docker group access: on the VM, run `sudo usermod -aG docker <username>` once (needs sudo there), then fully log out and reconnect
  (exit the SSH session and ssh back in) — group membership doesn't apply to
  an already-open session.

It then backgrounds the SSH tunnel (and closes it when the console exits) and
starts the local Streamlit console. Run it from the laptop only — it refuses
to run on `kwanz-ws` itself.

### Manual flow (same pieces, individually)

1. SSH access to kwanz-ws under your own account (you should already have
   one — `yang`, `faith`, `claris`, `heng` each have their own checkout under
   `/home/`).
2. From your own laptop, run `./.scripts/tunnel.sh` (replaces the old
   `mdx-tunnel-incident` alias) to forward the backend ports (agent 8000,
   NIMs 30081/30082, ingress 7777):
   ```bash
   ./.scripts/tunnel.sh
   ```
   Leave it running in its own terminal — it's supposed to sit there silently
   (that's correct, not stuck). Quick health check from a second terminal:
   ```bash
   ./.scripts/tunnel-check.sh
   # or, plain curl:
   curl http://localhost:8000/health
   # should return: {"value":{"isAlive":true}}
   ```
3. Run the console locally against the tunneled backend, per
   [`incident-console/README.md`](incident-console/README.md)'s "Real backend
   on kwanz-ws via SSH tunnel (Phase 4)" section. Each person runs their own
   console instance against the shared backend, not a single shared UI.

---

## 8. Current Status (as of 2026-09-24)

### 8.1 Feature / verification status

| Item | State |
|---|---|
| `incident-console` app (v1 Streamlit: catalog, report review, dashboard, human-eval; Postgres-backed, no offline mode) | Present; seed via `incident-console/scripts/seed_supabase.py` over `fixtures/data/*.csv` |
| `incident-console-v2` app (v2 Next.js: video upload, VLM analysis, incident reporting, review, dashboard, alerts, model-run history, ground-truth/severity evaluation) | Present (PR #72, merged 2026-09-21); local mock-backend loop documented and smoke-tested (`/`, `/reports`, `/dashboard`, `/notifications`, `/api/reports`, `/api/notifications`, `/api/health`); typecheck/build/test pass; direct-to-R2 upload fallback for real VST, which returns no object key (PR #81); VM-tunnel integration not yet verified end-to-end |
| Console schema (`db.py`: videos/queries/model_runs/incidents + evidence, ground-truth, match, review tables) | Present; authoritative for schema questions (shared by v1 and v2 via PostgREST) |
| Mock backend + local loop (`mock-backend/base_profile_mock`) | Present; verified loop documented (used by both v1 and v2) |
| Stock base-local deploy (one model per GPU, `hw-OTHER.env` sizing) | Verified working |
| Stock base-remote chat + VLM describe (`openai`-type, model above) | Verified working 2026-09-13 on corrected `--host-ip`: video upload to VST plus `video_understanding` through the remote VLM returned a correct description. Full `report_agent` path still needs a UI websocket (HITL), so it remains unverified headless. |
| Stock `search` profile (local and remote) | Verified working 2026-09-13 both modes; deploy commands in the mode docs §3 |
| `incident_report_gen` tool + `/analyze` API route | Built (PR #38, merged 2026-09-17); `vss-agent` runs natively on kwanz-ws from this repo's source (PR #70; `native-services.sh restart vss-agent` picks up code changes), which superseded PR #63's `--build` container rebuild — `start.sh` no longer builds images. Confirm the VM's active `vss-agent` process was restarted since PR #70 |
| Supabase / PostgREST integration | Migration validated against live project (PR #53); agent-side client ported from asyncpg to `supabase-py` PostgREST (PR #54, #57); `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` wired to agent (PR #62) for port-5432-safe access on kwanz-ws |
| P1 structured-extraction eval pipeline + 3-model VLM benchmark | Built (PR #83, merged 2026-09-24): `incident-console/scripts/eval_*.py` run P1/RP1 through the VLM gateway's upstream and score against `gt_*`; results and methodology in [`incident-console/docs/vlm_benchmark_results.md`](incident-console/docs/vlm_benchmark_results.md); raw working data under the gitignored `incident-console/eval_data/` |
| Tier 1 ground-truth evaluation | Built (PR #56, merged 2026-09-20); scores model runs against parallel `gt_*` tables via `eval_gt.py` / report detail UI (v1); v2 has its own evaluation form wired to the same tables |
| `dev-profile-incident` `config.yml`, `/search` API route | Planned (shared doc §§4-6); not yet built |
| `openai_vlm` missing-`base_url` patch (`base_url: ${VLM_BASE_URL}/v1` in `config.yml` + `config_rag.yml`) | Required; re-apply after any upstream sync |
| Remote free-tier 16-concurrent-request ceiling; hosted-model 12-images-per-prompt cap | Open constraints; remote report path loops/hangs past them |

> **v1 vs. v2 relationship:** Both consoles are currently present. v2 (Next.js) was added in PR #72 as a standalone replacement candidate — it uses the same backend contracts (vss-agent, VLM gateway, Supabase/PostgREST, R2) but does not share code with v1 (Streamlit). The v1 Streamlit container on `kwanz-ws` is a leftover from an earlier shared-UI setup and is no longer the intended path (see [Live deployment on kwanz-ws](#82-live-deployment-on-kwanz-ws)). Whether v2 fully supersedes v1 or both are maintained long-term is an open product decision; as of this writing, v1 remains the console with the established human-eval flow and Tier 1 GT evaluation UI, while v2 adds a modern App Router workspace with report-grounded chat, run comparison, and print-friendly reports. The team should clarify the intended roadmap.

### 8.2 Live deployment on kwanz-ws

The profile's backend (`vss-agent`, LLM/VLM NIMs, VIOS) runs on the shared `kwanz-ws` VM. **The `incident-console` UI runs on each team member's own laptop, not on the VM** — an SSH tunnel connects the two. This supersedes an earlier setup where the console ran as a shared container on the VM.

Docker appliance containers are up under `/srv/rise-up/vss/deploy/docker`, started via:

```bash
cd /srv/rise-up/vss/deploy/docker
sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <service>
```

(the root `compose.yml` in `deploy/docker` is the one to use — **not** the one inside `dev-profile-incident/`, which only defines the profile's own `incident-console` and `vlm-gateway` services)

`vss-agent` itself is **not** one of these containers — it runs natively via `.scripts/native-services.sh` (see [Native vs. Docker service split](#5-native-vs-docker-service-split)).

| Service / Container         | Role                                      | Status                                                                                                                                                                                                                    |
| ---------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `vss-agent` (native)         | AI agent — upload API, report generation | Up, healthy (`native-services.sh status`, not `docker compose ps`)                                                                                                                                                       |
| `vss-incident-console`      | the Streamlit UI                         | Up, but **superseded** — the console now runs on each person's own laptop instead; this VM container is a leftover from the earlier shared-VM-console setup, not the path to use going forward                            |
| `vss-vios-streamprocessing` | video decode/encode core                 | Up, healthy                                                                                                                                                                                                               |
| `vss-vios-nvstreamer`       | upload ingestion                         | Up                                                                                                                                                                                                                        |
| `vss-vios-ingress`          | nginx gateway for VST/storage API        | Up, healthy                                                                                                                                                                                                               |
| `vss-haproxy-ingress`       | public-facing ingress on port 7777       | Up                                                                                                                                                                                                                        |
| `vss-vios-postgres`         | VIOS's internal Postgres                 | Up, healthy                                                                                                                                                                                                               |
| `redis`                     | cache                                    | Up                                                                                                                                                                                                                        |
| `phoenix`                   | telemetry                                | Up                                                                                                                                                                                                                        |
| `vss-rtvi-embed`            | embedding service                        | Up, healthy (search/MVP2-related, not required for MVP1 but running)                                                                                                                                                    |

**Not running / broken** (see "Known issues" below): `nvidia-cosmos3-reasoner` (VLM — crash-looping), `nvidia-nemotron-nano-9b-v2` (LLM — never started), `vss-vios-sensor` (sensor-ms — never started), `vss-broker-health-check` (expected to fail, MVP2/Kafka-only).

#### Live config notes (`generated.env.remote`)

The untracked live env file on the VM diverges from the tracked `.env` template in a few places:

| Setting                      | Template value                                                        | Live value                       | Why                                                                                                                                                          |
| ---------------------------- | --------------------------------------------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `VSS_APPS_DIR`               | `/path/to/deploy/docker` (placeholder)                                | `/srv/rise-up/vss/deploy/docker` | Never filled in — broke every `include:` in the compose files                                                                                                |
| `VSS_DATA_DIR`               | `/path/to/vss-apps-data` (placeholder)                                | `/srv/rise-up/vss-apps-data`     | Same — needed for persistent volume mounts                                                                                                                   |
| `HOST_IP`                    | `<HOST_IP>` (placeholder)                                             | `10.131.1.5`                     | The VM's own internal address                                                                                                                                |
| `EXTERNAL_IP`                | derived from `HOST_IP` (wrong)                                        | `localhost`                      | Must differ from `HOST_IP` — this is what gets embedded in URLs handed back to your browser/tunnel                                                           |
| `VSS_AGENT_CONFIG_FILE`      | pointed at `dev-profile-search`'s config (zero report-gen capability) | `dev-profile-base`'s config      | Search's config never had `report_agent`/`video_report_gen` wired in at all                                                                                  |
| `REPORT_REFERENCE_BASE_DIR`  | unset (crashed startup)                                               | `/tmp`                           | Agent's `eval` config schema required a valid string, even though eval isn't actually used here                                                              |
| `STREAM_PROCESSOR_HTTP_PORT` | unset → defaulted to `30001`                                          | `10000`                          | nginx is hardcoded to proxy to `localhost:10000`, but the service's own default is `30001` — a pre-existing inconsistency in the repo's own shared `vst.env` |

### 8.3 Known issues

1. ~~**`vss-agent` now builds from source, but the VM hasn't redeployed yet.**
   `deploy/docker/services/agent/compose.yml`'s `vss-agent` service now carries
   a `build:` context (`services/agent/docker/Dockerfile`, context `services/`)
   alongside its `image:` tag, so `docker compose up -d --build vss-agent`
   rebuilds the container from this repo's own code (e.g. the `/analyze` route)
   instead of NVIDIA's locked prebuilt image. A plain `up -d` — no `--build` —
   still reuses whatever image already exists locally. What's currently running
   on the VM is still the prebuilt image; run one `--build` deploy there before
   relying on any agent-side code change.~~ **FIXED** — `vss-agent` now runs natively on kwanz-ws from source (PR #70), superseding PR #63's `start.sh --build` fix (`start.sh` no longer starts or builds a `vss-agent` container). Confirm the VM process was restarted after PR #70.
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

---

## 9. Verification Checklist

- **Upload a clip:** Appears in the catalog with correct status/count; lands in R2 and is retrievable.
- **Generate a report:** Every structured field populates; ambiguous input degrades (empty persons, unconfirmed start time).
- **Edit metadata, regenerate:** The new report reflects the edit.
- **Full-pipeline trigger:** Status moves through its lifecycle incl. an induced failure surfacing in the UI.
- **Verify a report:** Status flips; severity >= 4 raises a notification (default threshold, unconfirmed).
- **Search/filter, timestamp-jump, dashboard charts:** Reflect real rows; clearing filters returns the full set.
- **Human-eval sample:** Agreement rate matches a hand-computed value.
