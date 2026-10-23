# Incident Profile Operations & Runbook

This document is the operational guide and technical runbook for the incident profile (`dev-profile-incident`).
It documents deployment topology, runtime procedures, safe operations, SSH connectivity, live VM configuration
quirks, and verification checklists.

---

## 1. Environments and Access

The team shares a remote GPU development workstation (`kwanz-ws`), accessible via Tailscale VPN.

- **Host Hardware:** 2× NVIDIA RTX A6000 (48 GB VRAM each), AMD Threadripper PRO 5975WX (32 cores / 64 threads), 251 GiB RAM, 1.8 TB NVMe storage.
- **Tailscale Hostname:** `kwanz-ws.tailf3aa43.ts.net` (internal IP: `10.131.1.5`).
- **VM Working Directory:** `/srv/rise-up/vss` (root checkout).
- **NGC Credentials on VM:** `/srv/rise-up/.ngc_env` (load via `set -a; source /srv/rise-up/.ngc_env; set +a` or `source .scripts/ngc-env.sh`).
- **Deploy Flags Used on VM:** `--host-ip 10.131.1.5 --external-ip localhost --hardware-profile OTHER`.
- **Direct Base UI Tunnel (reference):** `ssh -N -L 7777:10.131.1.5:7777 <user>@kwanz-ws` -> browse `http://localhost:7777`.

---

## 2. Native vs. Docker Service Split

Fast-iterating application modules run directly as native processes on `kwanz-ws` rather than inside
Docker containers. This reduces code-change cycles from ~3-minute container rebuilds to ~2-second process restarts.
Heavy media appliances, proprietary toolchains, and backing infrastructure remain containerized.

**Policy Rule:** Run a service natively whenever feasible. Containers are reserved for services with proprietary system dependencies or standard off-the-shelf data appliances where native execution yields no development speedup.

Networking: nearly all containers use host networking (network_mode: host); exceptions are `phoenix` (bridge `mdx_default`, published 6006:6006) and `vss-rtvi-embed` (if started; published `${RTVI_EMBED_PORT}`=8017→8000). Native processes reach all of them on `localhost`.

| Category | Service | Port | Description & Execution Rationale |
|---|---|---|---|
| **Native Process (High Feasibility)** | `vss-agent` | `8000` | Core AI agent running via NAT framework (`nat serve`). Iterated constantly; ~2s native restart vs ~3min container build. |
| **Native Process (High Feasibility)** | `video-analytics-api` | `8081` | Optional analytics API (`node index.js`, gated by `ENABLE_ANALYTICS=true`). Fast Node.js runtime. |
| **Native Process (High Feasibility)** | `behavior-analytics` | none | Optional behavior analytics (`python3 apps/...`, `ENABLE_ANALYTICS=true`; Kafka consumer, no HTTP port). Fast Python runtime. |
| **Docker (Infeasible Natively)** | `vss-vios-streamprocessing` | `10000` | Hardware video decode/encode core and VST storage/upload API (GPU 0; receives chunked uploads via ingress). Bound to proprietary CUDA, GStreamer, and Triton toolchains. |
| **Docker (Infeasible Natively)** | `vss-vios-nvstreamer` | `31000` | NvStreamer RTSP file streamer (GPU 0; not in upload path; not routed by ingress/HAProxy). Bound to proprietary GStreamer pipelines. |
| **Docker (Infeasible Natively)** | `vss-vios-ingress` | `30888` | Nginx gateway for internal VIOS APIs: `/vst/api/v1/sensor` → sensor-ms :30000; other `/vst/api/v1` and `/vst/storage` → streamprocessing :10000. |
| **Docker (Infeasible Natively)** | `vss-vios-sensor` | `30000` | VST sensor registration service (`sensor-ms`, GPU 0; pinned in `compose.override.yml`, not started by `start.sh`). Ingress routes `/vst/api/v1/sensor/` to it. |
| **Docker (Infeasible Natively)** | `vss-vios-postgres` | Internal | VIOS internal database (Unix socket only). Pre-configured schema and user provisioning within VIOS ecosystem. |
| **Docker (Infeasible Natively)** | `vss-rtvi-cv` | `9000` | Stock DeepStream perception pipeline (`perception-2d-fusion`, GPU 0; pinned in `compose.override.yml`, but not started by `start.sh` and not used in MVP2). DeepStream / CUDA dependency stack. |
| **Docker (Infeasible Natively)** | `vss-rtvi-embed` | `8017` | Stock real-time video embedding generation (`rtvi-embed`, GPU 0, bridged port 8017→8000; pinned in `compose.override.yml`, but not started by `start.sh` and unused in MVP2). Triton / CUDA dependency stack. |
| **Docker (Standard Appliance)** | `redis` | Internal | In-memory cache and pub/sub message broker. Standard off-the-shelf appliance; zero development gain natively. |
| **Docker (Standard Appliance)** | `phoenix` | `6006` | Tracing, telemetry, and observability UI (bridged `mdx_default`, published 6006:6006). Standard standalone monitoring appliance. |
| **Docker (Standard Appliance)** | `vss-haproxy-ingress` | `7777` | Public gateway reverse proxy routing traffic to agent (:8000) and VIOS ingress (:30888). |
| **Docker (Standard Appliance)** | `kafka` | `9092` | Heavy event bus for analytics; always started by start.sh. |
| **Docker (Standard Appliance)** | `elasticsearch` | Internal | Heavy JVM data infrastructure for search indexing (`ENABLE_ANALYTICS=true`). Zero development gain natively. |

### Managing Native Services (`.scripts/native-services.sh`)

`.scripts/native-services.sh` is the VM-side lifecycle manager (`start`, `stop`, `restart`, `status`, `logs`).
It daemonizes processes with `nohup`, stores PID files under `/srv/rise-up/vss/.run/<service>.pid`, redirects
standard streams to `/srv/rise-up/vss/.run/<service>.log`, and polls health endpoints before reporting success.

**Multi-user concurrency & permissions:**
- Start operations serialise on `.run/native-services.lock` using `flock`, preventing TOCTOU startup races between teammates. Background daemonised processes close file descriptor 200 so the advisory lock is released upon launcher exit.
- Uses `umask 002` so created log files, PID files, and lock files are group-writable by any teammate in the shared VM group; pre-existing unwritable log and lock files are replaced before launching.
- A healthy `/health` response (`isAlive`) on the service port is treated as already running even if the PID file is missing or unreadable; startup is safely skipped and reported as already running.
- PID files are written atomically (`mktemp` then `mv`) and failed starts only remove the PID file if it matches the current run's PID.
- `status` and `status --porcelain` list only expected services: `vss-agent` by default, with `video-analytics-api` and `behavior-analytics` included only when `ENABLE_ANALYTICS=true` or when explicitly targeted. Output porcelain formatting is preserved for `start.sh` parsing. Tests: `.scripts/test-native-services.sh`.

```bash
# SSH into the workstation
ssh kwanz-ws
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts

# Check service status
./native-services.sh status

# Fast restart after editing agent code (~2 seconds)
./native-services.sh restart vss-agent

# Tail live agent logs
./native-services.sh logs vss-agent
```

### Pruning Retired Docker Images (`incident-operate-vm/scripts/prune-native-images.sh`)

Because `vss-agent`, `video-analytics-api`, and `behavior-analytics` run natively, their old container images
are dead weight on disk. Running `skills/incident-operate-vm/scripts/prune-native-images.sh` on the VM safely removes these unused images
and stopped containers after confirming the native virtual environment (`services/agent/.venv/bin/nat`) exists:

```bash
ssh kwanz-ws "bash /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/skills/incident-operate-vm/scripts/prune-native-images.sh"
```

If the native agent virtual environment is not present, the script prompts before proceeding. Use
`--non-interactive` only in an already-authorized automation context:

```bash
ssh kwanz-ws "bash /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/skills/incident-operate-vm/scripts/prune-native-images.sh --non-interactive"
```

### Virtual Environment & Editable Agent Reinstall (`services/agent`)

The native agent runs out of `/srv/rise-up/vss/services/agent/.venv` using `nat serve`.
For changes in `services/agent/src` to take effect across native process restarts (`native-services.sh restart vss-agent`), the package must be installed in editable mode (`editable: true` in `.venv/lib/python3.13/site-packages/vss_agents-*.dist-info/direct_url.json`).
Shared contract files are vendored in `services/agent/src/vss_agents/incident_contract/` from `contracts/` and synchronised with `python deploy/docker/developer-profiles/dev-profile-incident/contracts/sync.py` (`--check` mode verifies parity without copying).

Environment variables are captured at process start: editing `generated.env.remote` does not take effect until `native-services.sh restart vss-agent` sources the file. Live environment values can be inspected in `/proc/<pid>/environ`.

**VM Agent Reinstall Procedure:**
A full `uv sync` in `services/agent` on `kwanz-ws` fails because `nvdataset` only resolves from NVIDIA's internal artifactory. To relink `vss_agents` editably to the repo code and install dependencies:
```bash
cd /srv/rise-up/vss/services/agent
uv pip install --python .venv/bin/python --no-deps --index-url https://pypi.org/simple -e .
uv pip install --python .venv/bin/python supabase opencv-python-headless setuptools
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts
./native-services.sh restart vss-agent
```
Verify that `.venv/lib/python3.13/site-packages/vss_agents-*.dist-info/direct_url.json` contains `"editable": true` and `/proc/<pid>/environ` contains the Brev Switchyard URLs (`LLM_BASE_URL=https://switchyard-13doh4lsz.brevlab.com`, `VLM_BASE_URL=https://switchyard-13doh4lsz.brevlab.com`).

---

## 3. Laptop-to-VM Connectivity & SSH Troubleshooting

The primary UI (`incident-console-v2`) runs locally on developer laptops. Running `./start.sh --mode vm` is THE canonical way to set up everything from your laptop: it checks the VM deploy state over SSH, automatically self-heals any missing Docker or native services, opens the backgrounded SSH tunnel, and launches the console.

### SSH Port Tunneling (Manual / Standalone)

`start.sh --mode vm` manages the tunnel automatically. `start.sh` and `.scripts/tunnel.sh` detect the VM's LAN address over SSH (`ip -4 route get 1.1.1.1`, `src` field) unless `VSS_VM_IP` is set, and fall back to `10.131.1.5` if detection fails (currently `10.132.56.251`). If you need to open or test the tunnel manually for debugging (do **not** run this on `kwanz-ws` itself):

```bash
cd deploy/docker/developer-profiles/dev-profile-incident
./.scripts/tunnel.sh
```

To verify active tunnel ports:
```bash
./.scripts/tunnel-check.sh
```

Forwarded ports:
- `localhost:8000` -> `127.0.0.1:8000` on the VM (`vss-agent`: health, always-on search route `POST /api/v1/incidents/search`, and chat route `POST /api/v1/incidents/chat`)
- `localhost:7777` -> `<vm-ip>:7777` (`vss-haproxy-ingress`)

Tunnel listeners bind to the laptop loopback only (ssh `-L` default; do not add `GatewayPorts`). `incident-console-v2` is bound to `127.0.0.1:3200` by `start.sh` and the `dev`/`start` npm scripts, so nothing on the laptop network can reach it.

**`VSS_AGENT_HOST` on the VM:** the default is `127.0.0.1` because the agent has no authentication and holds the database admin key. `vss-haproxy-ingress` (host network) reaches it through `VSS_AGENT_BACKEND_HOST=127.0.0.1` (set in `compose.override.yml`; the shared haproxy template defaults it to `HOST_IP` for other profiles), and the tunnel forwards `-L 8000:127.0.0.1:8000`, which resolves on the VM. Other tunnel ports still target the VM LAN address. Rolling this out needs a haproxy recreate (`compose up -d`) and an agent restart (`native-services.sh restart vss-agent`); an old `VSS_AGENT_HOST=0.0.0.0` in `generated.env.remote` must be removed or changed. The browser-side `vss-ui` (which calls `${HOST_IP}:8000`) is not deployed in this profile.

### SSH Username Resolution & Troubleshooting

`start.sh` (in `vm` mode) and `.scripts/tunnel.sh` source `.scripts/vm-preflight.sh`, which resolves the SSH login target non-interactively with no prompts:
1. **Explicit Target:** If `VSS_SSH_TARGET` is set (e.g. `user@kwanz-ws.tailf3aa43.ts.net`), it is used directly.
2. **Explicit User:** If `VSS_SSH_USER` is set, it overrides the username while using `VSS_SSH_HOST` (default: `kwanz-ws`).
3. **SSH Config User:** If neither is set, the scripts inspect `~/.ssh/config` for `Host kwanz-ws` (via `ssh -G "${VSS_SSH_HOST}"`).
4. **Local Fallback:** Falls back to your local machine `$USER` / `whoami`.

**Mode Isolation & Preflight Check:**
- **Mock Mode (`--mode mock`; `local` is a deprecated alias):** Never sources `.scripts/vm-preflight.sh` and never touches SSH at all.
- **VM Mode (`--mode vm`):** Runs a fast SSH preflight check (`ssh -o BatchMode=yes -o ConnectTimeout=10 "$VSS_SSH_TARGET" true`, one retry on a timeout) before any tunnel, deploy check, env generation, npm install, or UI start. If it fails, `start.sh` aborts with a non-zero exit status, the raw SSH error, the classified cause and the next step (`.scripts/vm-preflight.sh`).

**VM unreachable: causes `start.sh` reports**

| Cause | Detected from | Next step it prints |
|---|---|---|
| Tailscale not logged in | `tailscale status --json` `BackendState` `NeedsLogin` | `tailscale up` / sign in |
| Tailscale stopped, or its daemon not running | `Stopped` / CLI cannot reach `tailscaled` | `tailscale up` / open the app |
| VM offline in the tailnet | the VM's peer entry has `Online: false` | power on the VM or restart its `tailscaled` |
| Host name does not resolve | ssh `Could not resolve hostname` | fix `HostName` in `~/.ssh/config`, MagicDNS, or `VSS_SSH_HOST` |
| SSH timeout | ssh `timed out` | `tailscale ping`; VM off, ACL or firewall |
| SSH server not running | ssh `Connection refused` | `sudo systemctl start ssh` from the VM console |
| No route | `No route to host` / `Network is unreachable` | check Wi-Fi/VPN/Tailscale |
| Login rejected | `Permission denied` | `VSS_SSH_USER`, `ssh-add -l`, authorised key |
| Host key changed | `Host key verification failed` | `ssh-keygen -R <host>` |

**Reachable VM, services down or missing:** `start.sh` lists what is missing and runs `.scripts/vm-ensure-docker.sh` on the VM (piped over SSH, so the laptop copy always runs). It clones the repo if `VSS_REPO_ROOT` has no checkout, stops with instructions if `generated.env.remote` is missing (secrets cannot be generated), rewrites a stale `HOST_IP` there to the VM's current address (timestamped `.bak-` copy first), pulls images that are not on the VM (`docker compose pull --ignore-buildable --include-deps --policy missing`; `mdx-*` images are built by `up`), and runs `docker compose up -d` under `VSS_COMPOSE_UP_TIMEOUT` (default 600 s). On a timeout it prints container states and the last Kafka / broker health-check log lines. Native services start under `VSS_NATIVE_START_TIMEOUT` (default 300 s). A stale `HOST_IP` was the cause of the 2026-10-18 hang: the Kafka broker health check never passed.

**Troubleshooting Gotchas:**
- **SSH Preflight Fails:** `start.sh` prints the cause and next step (table above). Beyond that, ensure your `Host kwanz-ws` entry in `~/.ssh/config` has the correct `HostName` and `User`.
- **Tunnel never comes up:** `start.sh` tells apart a laptop port already in use, a tunnel that exited (SSH connection or forward blocked, or `VSS_AGENT_HOST` on the VM bound to LAN instead of `127.0.0.1`: agent healthy on the VM but unreachable at loopback), an agent that crashed after starting (read `$VSS_REPO_ROOT/.run/vss-agent.log`), and a proxy failure (unreachable `vss-haproxy-ingress` on `${VSS_VM_IP}:7777`).
- **Wrong User Account:** Each teammate has a provisioned account on `kwanz-ws`. Configure `User <your-vm-username>` under `Host kwanz-ws` in `~/.ssh/config` (or set `export VSS_SSH_USER="<your-vm-username>"` in your shell rc). No interactive prompt is shown.

---

## 4. Safe Deployment Principles

1. **Deploy Exclusively via `start.sh` (or Direct Compose on VM):**
   `deploy/docker/scripts/dev-profile.sh` recognizes only stock profiles (`base`, `search`, `lvs`, `alerts`) and must NOT be used directly for the incident profile. `./start.sh --mode mock` and `./start.sh --mode vm` are THE standard way to set up and launch everything from your laptop. On `kwanz-ws` itself, backend appliances are managed via Docker Compose (`docker compose -f compose.yml -f developer-profiles/dev-profile-incident/compose.override.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <services>`) and native services via `.scripts/native-services.sh`.
2. **NEVER Run `dev-profile.sh down` on `kwanz-ws`:**
   `deploy/docker/scripts/dev-profile.sh down` executes `docker compose down -v` and deletes the entire persistent data directory
   (`VSS_DATA_DIR`), destroying tens of gigabytes of cached model weights. Always use:
   ```bash
   ./.scripts/down.sh
   # Or plain:
   docker compose -p mdx stop
   ```
   `./.scripts/down.sh` stops native services and runs `docker compose -p mdx stop` to stop containers without removing them (containers and their data are kept; restart is `./start.sh --mode vm`). Note that exited orphan containers are no longer cleaned up by `down.sh`; run `docker compose -p mdx down --remove-orphans` manually when a clean slate is wanted (still never `-v`).
3. **No Double Agent:**
   Never start the `vss-agent` Docker container when the native `vss-agent` process is already running on port 8000.
   `start.sh` intentionally excludes `vss-agent` from its `docker compose up` command.
4. **Cold Start & 503 Expectations:**
   Even in remote mode, cold startup requires time for VIOS, NvStreamer, and PostgreSQL to initialize. An HTTP 503
   during the first 60–90 seconds is normal readiness latency. Verify with `.scripts/health.sh` before modifying
   configuration.
5. **Permanent `unless-stopped` Restart Policy:**
   Upstream compose files configure several core appliances (`redis`, `vss-haproxy-ingress`, `centralizedb`, `vst-ingress`, `vss-ui`, `elasticsearch`, `logstash`, `kibana`) with `restart: always`. `streamprocessing-ms` has upstream `restart: unless-stopped`, but its `deploy.restart_policy.condition: always` takes precedence over `restart`. Both cause Docker to resurrect them on every host reboot even after a deliberate stop. In `dev-profile-incident/compose.override.yml`, the persistent appliances and stack services are set to `restart: unless-stopped`, and `streamprocessing-ms` also gets `deploy.restart_policy.condition: unless-stopped`. `nvstreamer-2d-fusion` keeps its upstream `on-failure` deploy policy, which already leaves it stopped after a reboot. When the stack is deliberately stopped (via `./.scripts/down.sh` or `docker compose -p mdx stop`), containers stay stopped across VM reboots.
6. **Stop on Last Exit (`start.sh` VM Mode):**
   In VM mode, `start.sh` registers active sessions by holding a shared flock on `$VSS_REPO_ROOT/.run/active-runs.lock` over SSH (`ssh -tt`); if registration cannot be confirmed within 10s (e.g. while another session is stopping the backend), `start.sh` aborts with a retry prompt. Exiting `start.sh` on the laptop (Ctrl-C, SIGTERM, normal exit) checks whether the session is the last active run on `kwanz-ws` using a kernel flock held over a background SSH connection. If no other active runs remain, `start.sh` runs `.scripts/vm-stop-backend.sh` over SSH, stopping native services (`native-services.sh stop`) and Docker appliance containers in-place via `docker stop`. Containers and data are kept; restart is `./start.sh --mode vm`.

---

## 5. VM Deployment Configuration Principles (`generated.env.remote`)

The untracked deployment environment file on `kwanz-ws` (`generated.env.remote`) configures container volume mounts, networking, and remote inference routing. Follow these standing principles when configuring the environment:

1. **Absolute App and Data Directories:** `VSS_APPS_DIR` must point to the absolute path of `deploy/docker` on the host filesystem so Docker Compose `include:` directives resolve correctly. `VSS_DATA_DIR` must point to the persistent data volume on the host.
2. **Dual-IP Network Topology:** `HOST_IP` must be set to the workstation's internal network IP (currently `10.132.56.251`, previously `10.131.1.5`; `.scripts/vm-ensure-docker.sh` detects and updates stale entries automatically) for inter-container communication, while `EXTERNAL_IP` must be `localhost` so response URLs function over developer SSH port tunnels.
3. **Base Config for Incident Profile:** `VSS_AGENT_CONFIG_FILE` must reference the `dev-profile-base` agent configuration; the shipped search configuration lacks the required `report_agent` and `video_report_gen` modules.
4. **Evaluation Directory Guard:** `REPORT_REFERENCE_BASE_DIR` must be defined (e.g. `/tmp`) to satisfy the NAT configuration schema and prevent startup crashes.
5. **Stream Processor Port Alignment:** `STREAM_PROCESSOR_HTTP_PORT` must be 10000 — the streamprocessing HTTP port that vss-vios-ingress (:30888) proxies `/vst/api/v1` and `/vst/storage` to.
6. **Remote Endpoint Format:** Remote Switchyard/Brev endpoints must omit trailing slashes and paths (e.g. `https://switchyard-...brevlab.com`, not ending with `/v1`).
7. **Client Type Enforcement:** Remote models must use `_type: openai` (`LLM_MODEL_TYPE=openai`, `VLM_MODEL_TYPE=openai`). Never use `_type: nim` against remote endpoints; the `nim_langchain` client leaks proprietary parameters (such as `verify_ssl`) into the HTTP JSON request body, which triggers HTTP 400 Bad Request errors on standard OpenAI-compatible endpoints.
8. **Search Embedding Credentials:** Search query embeddings and evidence crop loader embeddings use the NVIDIA-hosted endpoint (`https://integrate.api.nvidia.com/v1/embeddings`) with `NVIDIA_API_KEY` (or `NGC_CLI_API_KEY`) from `generated.env.remote`; the Brev key cannot call `/v1/embeddings`. Can be overridden with `EVIDENCE_EMBEDDING_BASE_URL`, `EVIDENCE_EMBEDDING_MODEL`, and `EVIDENCE_EMBEDDING_API_KEY`. The loader and search route must use the same model (`nvidia/llama-nemotron-embed-vl-1b-v2` at 1024 dimensions).
9. **Loopback Agent Bind:** `VSS_AGENT_HOST` defaults to `127.0.0.1` because the agent has no authentication and holds the database admin key. An old `VSS_AGENT_HOST=0.0.0.0` in `generated.env.remote` must be removed or updated to `127.0.0.1`; `vss-haproxy-ingress` reaches it via `VSS_AGENT_BACKEND_HOST=127.0.0.1` in `compose.override.yml`.
10. **GPU Device Allocation:** All VSS Docker appliances and native processes must be pinned strictly to GPU 0 (`CUDA_VISIBLE_DEVICES=0`, `NVIDIA_VISIBLE_DEVICES=0`, `RT_CV_DEVICE_ID=0`, `RT_EMBED_DEVICE_ID=0`, `FIXED_SHARED_DEVICE_IDS=0`) in `compose.override.yml`, `.env`, and scripts to ensure GPU 1 remains completely free for co-tenant training workloads on `kwanz-ws`. The running stack started by `start.sh` uses GPU 0 only (`streamprocessing-ms`, `nvstreamer-2d-fusion`, and native `vss-agent`), while unstarted stock services (`perception-2d-fusion`, `rtvi-embed`, `sensor-ms`) remain pinned to GPU 0 for safety.

> [!NOTE]
> For the current live environment values and deployed model configurations on `kwanz-ws`, see [Current Status & Known Issues (Live VM Configuration Snapshot)](status.md#6-live-vm-configuration-kwanz-ws).

---

## 6. Pre-Demo Checklist

Run through these checks before any live demo or presentation:

- [ ] **Health Endpoint Check:** Call `GET /api/health` on `incident-console-v2` (`curl -s http://localhost:3200/api/health`). All core services (`database`, `storage`, `inference`, `agent`) should report `true`. If any status reports `degraded`, treat it as an active warning and investigate before presenting.
- [ ] **Search Configuration & UX:** Keep search `top_k` set to 5–10 (each candidate hit adds ~1 s of critic launch delay spacing, so high `top_k` values scale latency linearly). Ensure the frontend displays a loading state during query evaluation.
- [ ] **Recorded Fallback Asset:** Keep a pre-recorded demo video or offline screencast ready in case remote inference or network connectivity degrades during the demo.
- [ ] **Evidence Rows:** Search needs `evidence_crops` rows, which the console rebuilds when a revision is made official (it calls the agent's `evidence-embeddings` endpoint). Mark the demo incidents official before the demo, then confirm a search returns them.

---

## 7. End-to-End Verification Checklist

Verify deployment health against this checklist before declaring a build ready:

- [ ] **Video Ingestion:** Upload an `.mp4` clip via `incident-console-v2`. Verify that chunked upload succeeds,
      the clip is stored in Cloudflare R2 as a classification-neutral `uploads/<sensorId>/<uuid><ext>` key in both modes, `HeadObject` reports a nonzero size, and a playback URL generates.
- [ ] **Automated Report Generation:** Trigger incident analysis. Verify all structured fields populate
      (type, severity, confidence, summary, timeline, entities, instruments, assets). Confirm ambiguous footage
      gracefully degrades (e.g. empty persons array, unconfirmed start time).
- [ ] **Persistence Read-Back:** Confirm `POST /api/analysis` returns 200 only after `videos`, `model_runs`,
      `report_revisions` (the AI revision) can be read back and `videos.filepath` exactly matches the submitted R2 key.
- [ ] **Re-Generation:** Re-generate with a different model and a reviewer prompt, and confirm a new AI revision appears in
      History while earlier revisions remain openable.
- [ ] **Pipeline Error Handling:** Induce an invalid video or disconnect the tunnel; verify that the frontend surfaces
      descriptive error messaging without crashing.
- [ ] **Human Revisions:** Edit a report and Save, open an older revision in History and Restore it, then make one revision
      official. Verify each creates a new revision with the reviewer's name and time, and that only one is official.
- [ ] **Filtering & Dashboard:** Filter report library by incident type, severity, and date range. Confirm that
      counts match database records and clearing filters restores the full catalog.

---

## 8. Troubleshooting Order & Diagnostics

When troubleshooting unexpected failures:

1. **Check Process Status:**
   ```bash
   ./.scripts/status.sh
   ./.scripts/native-services.sh status
   ```
2. **Verify Agent Health:**
   ```bash
   ./.scripts/health.sh
   # Or directly:
   curl -s http://localhost:8000/health
   ```
3. **Inspect Application Logs:**
   ```bash
   # Native agent logs
   ./.scripts/logs.sh vss-agent

   # Docker appliance logs
   docker logs --tail 100 vss-haproxy-ingress
   docker logs --tail 100 vss-vios-ingress
   ```
4. **Handle Partial Deploys:**
   If `start.sh` reports a partial deployment, let its self-healing logic attempt to bring up missing services,
   or inspect the missing service output and restart it manually with `.scripts/native-services.sh restart <svc>`
   or `.scripts/rebuild-svc.sh <service>` (which layers `compose.override.yml`). Do not force-redeploy blindly over inconsistent state.
