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

Networking: nearly all containers use host networking (network_mode: host); exceptions are `phoenix` (bridge `mdx_default`, published 6006:6006) and `vss-rtvi-embed` (published `${RTVI_EMBED_PORT}`=8017→8000). Native processes reach all of them on `localhost`.

| Category | Service | Port | Description & Execution Rationale |
|---|---|---|---|
| **Native Process (High Feasibility)** | `vss-agent` | `8000` | Core AI agent running via NAT framework (`nat serve`). Iterated constantly; ~2s native restart vs ~3min container build. |
| **Native Process (High Feasibility)** | `video-analytics-api` | `8081` | Optional analytics API (`node index.js`, gated by `ENABLE_ANALYTICS=true`). Fast Node.js runtime. |
| **Native Process (High Feasibility)** | `behavior-analytics` | none | Optional behavior analytics (`python3 apps/...`, `ENABLE_ANALYTICS=true`; Kafka consumer, no HTTP port). Fast Python runtime. |
| **Docker (Infeasible Natively)** | `vss-vios-streamprocessing` | `10000` | Hardware video decode/encode core and VST storage/upload API (nvidia runtime, all GPUs visible; receives chunked uploads via ingress). Bound to proprietary CUDA, GStreamer, and Triton toolchains. |
| **Docker (Infeasible Natively)** | `vss-vios-nvstreamer` | `31000` | NvStreamer RTSP file streamer (GPU 0; not in upload path; not routed by ingress/HAProxy). Bound to proprietary GStreamer pipelines. |
| **Docker (Infeasible Natively)** | `vss-vios-ingress` | `30888` | Nginx gateway for internal VIOS APIs: `/vst/api/v1/sensor` → sensor-ms :30000; other `/vst/api/v1` and `/vst/storage` → streamprocessing :10000. |
| **Docker (Infeasible Natively)** | `vss-vios-sensor` | `30000` | VST sensor registration service (`sensor-ms`, nvidia runtime). Ingress routes `/vst/api/v1/sensor/` to it. |
| **Docker (Infeasible Natively)** | `vss-vios-postgres` | Internal | VIOS internal database (Unix socket only). Pre-configured schema and user provisioning within VIOS ecosystem. |
| **Docker (Infeasible Natively)** | `vss-rtvi-cv` | `9000` | Real-time computer vision perception pipeline (GPU 0). DeepStream / CUDA dependency stack. |
| **Docker (Infeasible Natively)** | `vss-rtvi-embed` | `8017` | Real-time video embedding generation (GPU 1, bridged port 8017→8000). Triton / CUDA dependency stack. |
| **Docker (Standard Appliance)** | `redis` | Internal | In-memory cache and pub/sub message broker. Standard off-the-shelf appliance; zero development gain natively. |
| **Docker (Standard Appliance)** | `phoenix` | `6006` | Tracing, telemetry, and observability UI (bridged `mdx_default`, published 6006:6006). Standard standalone monitoring appliance. |
| **Docker (Standard Appliance)** | `vss-haproxy-ingress` | `7777` | Public gateway reverse proxy routing traffic to agent (:8000) and VIOS ingress (:30888). |
| **Docker (Standard Appliance)** | `kafka` | `9092` | Heavy event bus for analytics; always started by start.sh. |
| **Docker (Standard Appliance)** | `elasticsearch` | Internal | Heavy JVM data infrastructure for search indexing (`ENABLE_ANALYTICS=true`). Zero development gain natively. |

### Managing Native Services (`.scripts/native-services.sh`)

`.scripts/native-services.sh` is the VM-side lifecycle manager (`start`, `stop`, `restart`, `status`, `logs`).
It daemonizes processes with `nohup`, stores PID files under `/srv/rise-up/vss/.run/<service>.pid`, redirects
standard streams to `/srv/rise-up/vss/.run/<service>.log`, and polls health endpoints before reporting success.

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

### Pruning Retired Docker Images (`.scripts/prune-native-images.sh`)

Because `vss-agent`, `video-analytics-api`, and `behavior-analytics` run natively, their old container images
are dead weight on disk. Running `.scripts/prune-native-images.sh` on the VM safely removes these unused images
and stopped containers after confirming the native virtual environment (`services/agent/.venv/bin/nat`) exists:

```bash
ssh kwanz-ws "bash /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts/prune-native-images.sh"
```

### Virtual Environment & Editable Agent Reinstall (`services/agent`)

The native agent runs out of `/srv/rise-up/vss/services/agent/.venv` using `nat serve`.
For changes in `services/agent/src` to take effect across native process restarts (`native-services.sh restart vss-agent`), the package must be installed in editable mode (`editable: true` in `.venv/lib/python3.13/site-packages/vss_agents-*.dist-info/direct_url.json`).

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

`start.sh --mode vm` manages the tunnel automatically. If you need to open or test the tunnel manually for debugging (do **not** run this on `kwanz-ws` itself):

```bash
cd deploy/docker/developer-profiles/dev-profile-incident
./.scripts/tunnel.sh
```

To verify active tunnel ports:
```bash
./.scripts/tunnel-check.sh
```

Forwarded ports:
- `localhost:8000` -> `10.131.1.5:8000` (`vss-agent`)
- `localhost:7777` -> `10.131.1.5:7777` (`vss-haproxy-ingress`)
- `localhost:30081` -> `10.131.1.5:30081` (LLM inference; unused in Brev mode — nothing listens on VM)
- `localhost:30082` -> `10.131.1.5:30082` (VLM inference; unused in Brev mode — nothing listens on VM)

### SSH Username Resolution & Troubleshooting

`start.sh` (in `vm` mode) and `.scripts/tunnel.sh` resolve the SSH login target using `.scripts/resolve-ssh-target.sh` non-interactively with no prompts:
1. **Explicit Target:** If `VSS_SSH_TARGET` is set (e.g. `user@kwanz-ws.tailf3aa43.ts.net`), it is used directly.
2. **Explicit User:** If `VSS_SSH_USER` is set, it overrides the username while using `VSS_SSH_HOST` (default: `kwanz-ws`).
3. **SSH Config User:** If neither is set, the scripts inspect `~/.ssh/config` for `Host kwanz-ws` (via `ssh -G "${VSS_SSH_HOST}"`).
4. **Local Fallback:** Falls back to your local machine `$USER` / `whoami`.

**Mode Isolation & Preflight Check:**
- **Local Mode (`--mode local`):** Never sources `resolve-ssh-target.sh` and never touches SSH at all.
- **VM Mode (`--mode vm`):** Runs a fast SSH preflight check (`ssh -o BatchMode=yes -o ConnectTimeout=10 "$VSS_SSH_TARGET" true`) before any tunnel, deploy check, env generation, npm install, or UI start. If the check fails, `start.sh` aborts immediately with non-zero exit status and an actionable error message.

**Troubleshooting Gotchas:**
- **SSH Preflight Fails:** Ensure Tailscale is active and connected, and verify your `Host kwanz-ws` entry in `~/.ssh/config` is configured with the correct `HostName` and `User`.
- **Wrong User Account:** Each teammate has a provisioned account on `kwanz-ws`. Configure `User <your-vm-username>` under `Host kwanz-ws` in `~/.ssh/config` (or set `export VSS_SSH_USER="<your-vm-username>"` in your shell rc). No interactive prompt is shown.

---

## 4. Safe Deployment Principles

1. **Deploy Exclusively via `start.sh` (or Direct Compose on VM):**
   `deploy/docker/scripts/dev-profile.sh` recognizes only stock profiles (`base`, `search`, `lvs`, `alerts`) and must NOT be used directly for the incident profile. `./start.sh --mode local` and `./start.sh --mode vm` are THE standard way to set up and launch everything from your laptop. On `kwanz-ws` itself, backend appliances are managed via Docker Compose (`docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <services>`) and native services via `.scripts/native-services.sh`.
2. **NEVER Run `dev-profile.sh down` on `kwanz-ws`:**
   `deploy/docker/scripts/dev-profile.sh down` executes `docker compose down -v` and deletes the entire persistent data directory
   (`VSS_DATA_DIR`), destroying tens of gigabytes of cached model weights. Always use:
   ```bash
   ./.scripts/down.sh
   # Or plain:
   docker compose down
   ```
3. **No Double Agent:**
   Never start the `vss-agent` Docker container when the native `vss-agent` process is already running on port 8000.
   `start.sh` intentionally excludes `vss-agent` from its `docker compose up` command.
4. **Cold Start & 503 Expectations:**
   Even in remote mode, cold startup requires time for VIOS, NvStreamer, and PostgreSQL to initialize. An HTTP 503
   during the first 60–90 seconds is normal readiness latency. Verify with `.scripts/health.sh` before modifying
   configuration.

---

## 5. VM Deployment Configuration Principles (`generated.env.remote`)

The untracked deployment environment file on `kwanz-ws` (`generated.env.remote`) configures container volume mounts, networking, and remote inference routing. Follow these standing principles when configuring the environment:

1. **Absolute App and Data Directories:** `VSS_APPS_DIR` must point to the absolute path of `deploy/docker` on the host filesystem so Docker Compose `include:` directives resolve correctly. `VSS_DATA_DIR` must point to the persistent data volume on the host.
2. **Dual-IP Network Topology:** `HOST_IP` must be set to the workstation's internal network IP (`10.131.1.5`) for inter-container communication, while `EXTERNAL_IP` must be `localhost` so response URLs function over developer SSH port tunnels.
3. **Base Config for Incident Profile:** `VSS_AGENT_CONFIG_FILE` must reference the `dev-profile-base` agent configuration; the shipped search configuration lacks the required `report_agent` and `video_report_gen` modules.
4. **Evaluation Directory Guard:** `REPORT_REFERENCE_BASE_DIR` must be defined (e.g. `/tmp`) to satisfy the NAT configuration schema and prevent startup crashes.
5. **Stream Processor Port Alignment:** `STREAM_PROCESSOR_HTTP_PORT` must be 10000 — the streamprocessing HTTP port that vss-vios-ingress (:30888) proxies `/vst/api/v1` and `/vst/storage` to.
6. **Remote Endpoint Format:** Remote Switchyard/Brev endpoints must omit trailing slashes and paths (e.g. `https://switchyard-...brevlab.com`, not ending with `/v1`).
7. **Client Type Enforcement:** Remote models must use `_type: openai` (`LLM_MODEL_TYPE=openai`, `VLM_MODEL_TYPE=openai`). Never use `_type: nim` against remote endpoints; the `nim_langchain` client leaks proprietary parameters (such as `verify_ssl`) into the HTTP JSON request body, which triggers HTTP 400 Bad Request errors on standard OpenAI-compatible endpoints.

> [!NOTE]
> For the current live environment values and deployed model configurations on `kwanz-ws`, see [Current Status & Known Issues (Live VM Configuration Snapshot)](status.md#4-live-vm-configuration-snapshot-kwanz-ws).

---

## 6. End-to-End Verification Checklist

Verify deployment health against this checklist before declaring a build ready:

- [ ] **Video Ingestion:** Upload an `.mp4` clip via `incident-console-v2`. Verify that chunked upload succeeds,
      the clip is stored in Cloudflare R2 (vm mode: `uploads/<sensorId>/<uuid><ext>`; local mock: `anomaly/<category>/<filename>`), and a playback URL generates.
- [ ] **Automated Report Generation:** Trigger incident analysis. Verify all structured fields populate
      (type, severity, confidence, summary, timeline, entities, instruments, assets). Confirm ambiguous footage
      gracefully degrades (e.g. empty persons array, unconfirmed start time).
- [ ] **Metadata Editing & Re-Analysis:** Modify input metadata, re-run analysis, and confirm that a new model run ID
      is generated and prior runs remain accessible in the run picker.
- [ ] **Pipeline Error Handling:** Induce an invalid video or disconnect the tunnel; verify that the frontend surfaces
      descriptive error messaging without crashing.
- [ ] **Human Review & Verification:** Transition report review status (`unreviewed` -> `under review` -> `verified`).
      Verify that reports with severity >= 4 generate a notification entry in `notifications`.
- [ ] **Filtering & Dashboard:** Filter report library by incident type, severity, and date range. Confirm that
      counts match database records and clearing filters restores the full catalog.
- [ ] **Ground-Truth Evaluation:** Open the evaluation interface for an incident with ground truth (`gt_incidents`).
      Confirm that exact type/severity match, LLM-judge description evaluation, and entity/instrument/asset
      matching metrics display correctly.

---

## 7. Troubleshooting Order & Diagnostics

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
   or `docker compose up -d <service>`. Do not force-redeploy blindly over inconsistent state.
