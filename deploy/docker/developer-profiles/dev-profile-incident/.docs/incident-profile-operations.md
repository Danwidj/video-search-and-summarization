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
Heavy media appliances and backing infrastructure remain containerized.

| Execution Mode | Service | Port | Description & Role |
|---|---|---|---|
| **Native Process** (`kwanz-ws`) | `vss-agent` | `8000` | Core AI agent running via NAT framework (`nat serve`) |
| **Native Process** (`kwanz-ws`) | `video-analytics-api` | `8081` | Optional analytics API (`node index.js`, gated by `ENABLE_ANALYTICS=true`) |
| **Native Process** (`kwanz-ws`) | `behavior-analytics` | `8080` | Optional behavior analytics (`python3 apps/...`, `ENABLE_ANALYTICS=true`) |
| **Docker Appliance** | `vss-haproxy-ingress` | `7777` | Public gateway reverse proxy |
| **Docker Appliance** | `vss-vios-streamprocessing` | Internal | Hardware video decode/encode core (GPU 0) |
| **Docker Appliance** | `vss-vios-nvstreamer` | Internal | Video ingestion and RTSP/WebRTC publisher (GPU 0) |
| **Docker Appliance** | `vss-vios-ingress` | `10000` | Nginx gateway for internal VIOS storage APIs |
| **Docker Appliance** | `vss-vios-postgres` | Internal | VIOS internal database |
| **Docker Appliance** | `redis` | Internal | State cache and message broker |
| **Docker Appliance** | `phoenix` | `6006` | Tracing, telemetry, and observability |
| **Docker Appliance** | `elasticsearch`, `kafka` | Internal | Search indexing and streaming event bus (`ENABLE_ANALYTICS=true`) |

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

---

## 3. Laptop-to-VM Connectivity & SSH Troubleshooting

The primary UI (`incident-console-v2`) runs locally on developer laptops. VM mode connects the laptop to
`kwanz-ws` through an SSH tunnel.

### SSH Port Tunneling

Run the tunnel from your laptop (do **not** run this on `kwanz-ws` itself):

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
- `localhost:30081` -> `10.131.1.5:30081` (LLM inference)
- `localhost:30082` -> `10.131.1.5:30082` (VLM inference)

### SSH Username Resolution & Troubleshooting

`start.sh` and `.scripts/tunnel.sh` resolve the SSH login target using `.scripts/resolve-ssh-target.sh`:
1. **Explicit Target:** If `VSS_SSH_TARGET` is set (e.g. `user@kwanz-ws.tailf3aa43.ts.net`), it is used directly.
2. **Explicit User:** If `VSS_SSH_USER` is set, it overrides the username while using `VSS_SSH_HOST` (default: `kwanz-ws`).
3. **SSH Config / Prompt:** If neither is set, the scripts inspect `~/.ssh/config` for `Host kwanz-ws`. If missing,
   they prompt interactively with your local machine `$USER` as default.

**Troubleshooting Gotchas:**
- **Prompt Does Not Appear:** A stale `VSS_SSH_TARGET` or `VSS_SSH_USER` is set in your current shell.
  Run `unset VSS_SSH_TARGET VSS_SSH_USER` to restore the interactive prompt.
- **Wrong Default User:** Your local laptop username may not match your provisioned account on `kwanz-ws`.
  Do not blindly accept the default prompt if your VM username differs; set `export VSS_SSH_USER="<your-vm-username>"`
  in your laptop's `.bashrc` or `.zshrc`.

---

## 4. Safe Deployment Principles

1. **Do NOT Use `dev-profile.sh` Directly for Incident Profile:**
   `dev-profile.sh` recognizes only stock profiles (`base`, `search`, `lvs`, `alerts`). Deploying
   `dev-profile-incident` is performed via `start.sh --mode vm` or directly via Docker Compose using the
   root `deploy/docker/compose.yml` with `--env-file developer-profiles/dev-profile-incident/generated.env.remote`.
2. **NEVER Run `dev-profile.sh down` on `kwanz-ws`:**
   `dev-profile.sh down` executes `docker compose down -v` and deletes the entire persistent data directory
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

## 5. Live VM Configuration Notes (`generated.env.remote`)

The untracked live environment file on `kwanz-ws` (`generated.env.remote`) requires specific overrides
diverging from repository placeholders:

| Setting | Repository Default | VM Live Value | Operational Rationale |
|---|---|---|---|
| `VSS_APPS_DIR` | `/path/to/deploy/docker` | `/srv/rise-up/vss/deploy/docker` | Absolute path required for Docker Compose `include:` directives. |
| `VSS_DATA_DIR` | `/path/to/vss-apps-data` | `/srv/rise-up/vss-apps-data` | Host directory for persistent container volume mounts. |
| `HOST_IP` | `<HOST_IP>` | `10.131.1.5` | Workstation's internal IP. Required for inter-container communication. |
| `EXTERNAL_IP` | Derived from `HOST_IP` | `localhost` | URL host embedded in responses handed back to browser and SSH tunnel. |
| `VSS_AGENT_CONFIG_FILE` | (Pointed at search) | `dev-profile-base` config | Shipped search config lacks `report_agent`/`video_report_gen`. |
| `REPORT_REFERENCE_BASE_DIR`| Unset | `/tmp` | Required by agent evaluation configuration schema to avoid startup crash. |
| `STREAM_PROCESSOR_HTTP_PORT`| Defaults to `30001` | `10000` | Nginx ingress proxies to `localhost:10000`; streamprocessor must listen on 10000. |

---

## 6. End-to-End Verification Checklist

Verify deployment health against this checklist before declaring a build ready:

- [ ] **Video Ingestion:** Upload an `.mp4` clip via `incident-console-v2`. Verify that chunked upload succeeds,
      the clip is stored in Cloudflare R2 under `uploads/<sensorId>/<uuid>.mp4`, and a playback URL generates.
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
