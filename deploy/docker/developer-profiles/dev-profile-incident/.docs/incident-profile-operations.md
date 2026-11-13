# Incident Profile Operations & Runbook

How the incident profile (`dev-profile-incident`) is deployed and operated: what runs on the VM, how the laptop reaches it, the rules for `.env.remote`, safe operations and the verification checklist.

## 1. Environments and Access

The backend runs on a shared GPU workstation (the VM), reached over Tailscale.

- **Hardware:** 2× NVIDIA RTX A6000 (48 GB VRAM each). VSS uses GPU 0 only ([GPU rule](#5-vm-deployment-configuration-principles-envremote), item 10).
- **Tailscale hostname:** `<vm-host>.<tailnet>.ts.net` (the LAN address changes with DHCP).
- **VM working directory:** `/srv/rise-up/vss` (root checkout).
- **NGC credentials on the VM:** `/srv/rise-up/.ngc_env` (`source .scripts/ngc-env.sh`; `VSS_NGC_ENV` overrides the file).

## 2. Native vs. Docker Service Split

`vss-agent` runs as a native process on the VM, so a code change needs a ~2-second restart instead of a container rebuild. Phoenix (the trace viewer used for eval) and the person-tracking stack run in Docker. VIOS/VST, HAProxy and Redis are not deployed: `start.sh` neither starts nor checks them. The split is drawn in [`architecture.md`](architecture.md#native-processes-and-containers); the ports are in [`vm-api-contracts.md`](vm-api-contracts.md#tunnel).

### Managing Native Services (`.scripts/native-services.sh`)

The VM-side lifecycle manager (`start`, `stop`, `restart`, `status`, `logs`). It daemonises each process with `nohup`, keeps `<service>.pid` and `<service>.log` under `/srv/rise-up/vss/.run/` (`VSS_RUN_DIR` overrides the directory) and polls the health endpoint before reporting success.

```bash
ssh "$VSS_SSH_HOST"
cd /srv/rise-up/vss/deploy/docker/developer-profiles/dev-profile-incident/.scripts
./native-services.sh status              # what is running
./native-services.sh restart vss-agent   # after editing agent code (~2 seconds)
./native-services.sh logs vss-agent      # tail the agent log
```

- **Shared VM:** starts serialise on `.run/native-services.lock` (`flock`), and a healthy `/health` on the service port counts as already running.
- **Environment is captured at process start:** an edit to `.env.remote` takes effect only after `native-services.sh restart vss-agent`.

### Person-tracking stack (`.scripts/tracking-stack.sh`, `ENABLE_TRACKING=true`)

On by default in vm mode: `./start.sh --mode vm` runs `tracking-stack.sh start` on the VM after Phoenix, and the stack keeps running when `start.sh` exits. It is Kafka, Elasticsearch, Logstash, NvStreamer, perception and the video-analytics API.

```bash
./tracking-stack.sh start               # stage the RT-DETR model if missing, bring up, wait for ready
./tracking-stack.sh status              # perception stream-count, :8081/livez, mdx-* indices, NvStreamer streams
./tracking-stack.sh restart-perception  # only perception-2d-fusion, then wait for ready
./tracking-stack.sh stop                # stop by name; keeps containers, volumes and built engines
```

- **First start** stages the RT-DETR model with `ngc` (key `NGC_CLI_API_KEY` from the env file) and builds TensorRT engines (about 7 to 10 minutes); later starts take about 90 s.
- **Cost:** GPU 0 holds about 7.6 GB while the perception container is up, and the images take about 40 GB.
- **HDR clips crash DeepStream** (BT.2020/HLG, as iPhone HDR records). Convert HDR to BT.709 before NvStreamer, or skip tracking for it.
- **Pipeline dies, container lives:** after a crash `/api/v1/ready` still says YES. Health is `stream-count` in `status`; run `restart-perception` when it is 0 and a stream produces no frames.
- **One stack per host:** the video-analytics API container takes port 8081 from the native `video-analytics-api` (`ENABLE_ANALYTICS`); do not run both.

### Default analysis stack in vm mode

One `./start.sh --mode vm` brings up person tracking and the caption pass. Each is on by default and can be turned off on its own; the analysis still runs without it.

| Piece | Where the default lives | Turn it off |
|---|---|---|
| Tracking stack (perception containers) | `start.sh`: `ENABLE_TRACKING` defaults to `true` in vm mode | `ENABLE_TRACKING=false ./start.sh` (the agent then reports `tracking.skipped`) |
| Tracking in the agent | `native-services.sh`: `INCIDENT_TRACKING_ENABLED=true` | `INCIDENT_TRACKING_ENABLED=false` in `.env.remote` (ask first), then restart the agent |
| Caption pass (clips over 30 s) | `native-services.sh`: `INCIDENT_CHUNKING_ENABLED=1` | `INCIDENT_CHUNKING_ENABLED=0` in `.env.remote` (ask first), then restart the agent |

Before it starts the agent, `native-services.sh` also installs what the agent needs when missing: `ffmpeg` and `ffprobe` (`.scripts/media-tools.sh`; without them the agent skips the caption pass and tracking) and the NanoTrack model files for object tracking (`.scripts/tracker-models.sh`). Never `apt-get install` ffmpeg on the shared VM.

### Pruning Retired Docker Images

`skills/incident-operate-vm/scripts/prune-native-images.sh`, run on the VM, removes the unused images and stopped containers of the services that now run natively. It prompts first when the native virtual environment is missing.

### Editable Agent Reinstall (`services/agent`)

The native agent runs out of `/srv/rise-up/vss/services/agent/.venv` with `nat serve`, installed in editable mode so changes in `services/agent/src` take effect on restart. The VM venv was built by hand and a full `uv sync` would replace it, so relink it with:

The commands are in the [incident-operate-vm skill](../skills/incident-operate-vm/SKILL.md).

Then `direct_url.json` in the package's `dist-info` contains `"editable": true`. The contract files and prompts the agent uses are vendored from `contracts/`; `contracts/sync.py --check` verifies parity.

## 3. Laptop-to-VM Connectivity & SSH Troubleshooting

The console (`incident-console-v2`) runs on the laptop. `./start.sh --mode vm` sets everything up: it checks the VM over SSH, starts any missing Docker or native service, opens the SSH tunnel in the background and launches the console on `127.0.0.1:3200`.

- **Production console:** `./start.sh --mode vm --prod` runs `next build` then `next start` instead of `npm run dev`. Use it to demo or for a long session. It does not pick up a code change: stop `start.sh` and run it again, which always rebuilds.
- **Tunnel:** `start.sh` forwards only `localhost:8000` to the agent on the VM loopback. To open or test it by hand (never on the VM itself): `./.scripts/tunnel.sh`, then `./.scripts/tunnel-check.sh`. Listeners bind to the laptop loopback only; do not add `GatewayPorts`.

### SSH login

`start.sh` and `.scripts/tunnel.sh` source `.scripts/vm-preflight.sh`, which resolves the SSH target with no prompt: `VSS_SSH_TARGET` as is; else `VSS_SSH_USER` with `VSS_SSH_HOST` (no default: set it in `.env.local` or the environment to your own host or SSH config alias); else the `User` of that host's entry in `~/.ssh/config`; else your local `$USER`.

Before any tunnel, deploy check or UI start, `start.sh` runs `ssh -o BatchMode=yes -o ConnectTimeout=10 "$VSS_SSH_TARGET" true` (one retry on a timeout). If it fails, `start.sh` exits non-zero with the raw SSH error, the cause and the next step. The causes it tells apart are Tailscale not logged in or stopped, the VM offline in the tailnet, a host name that does not resolve, an SSH timeout, a refused connection, no route, a rejected login and a changed host key.

### Reachable VM, services down or missing

`start.sh` lists what is missing and runs `.scripts/vm-ensure-docker.sh` on the VM (piped over SSH, so the laptop copy always runs). It:

- clones the repo if `VSS_REPO_ROOT` has no checkout;
- stops with instructions if `.env.remote` (or the old name `generated.env.remote`) is missing, because secrets cannot be generated;
- rewrites a stale, blank or missing `HOST_IP` there to the VM's current address (timestamped `.bak-` copy first);
- pulls images that are not on the VM and runs `docker compose up -d --yes` under `VSS_COMPOSE_UP_TIMEOUT` (default 600 s).

Its exit codes: 10 repo, 11 env file, 12 docker, 13 pull, 14 up, 124 timeout.

**Tunnel never comes up:** `start.sh` tells apart a laptop port already in use, a tunnel that exited (SSH forward blocked, or `VSS_AGENT_HOST` on the VM bound to LAN instead of `127.0.0.1`), and an agent that crashed after starting (read `$VSS_REPO_ROOT/.run/vss-agent.log`).

## 4. Safe Deployment Principles

1. **Deploy only with `start.sh`.** `deploy/docker/scripts/dev-profile.sh` knows only the stock profiles and must not be used for the incident profile.
2. **Never run `dev-profile.sh down` on the VM.** It executes `docker compose down -v` and deletes the entire persistent data directory (`VSS_DATA_DIR`), destroying tens of gigabytes of cached model weights. Use `./.scripts/down.sh`, which stops native services and runs `docker compose -p mdx stop` (containers and their data are kept). Never pass `-v`.
3. **No double agent.** Never start the `vss-agent` Docker container while the native `vss-agent` runs on port 8000.
4. **Cold start.** An HTTP 503 during the agent's first 60-90 seconds is normal. Check with `.scripts/health.sh` before changing configuration.
5. **Stopped means stopped.** `compose.override.yml` sets the persistent appliances to `restart: unless-stopped`, so a stack stopped on purpose stays stopped across VM reboots.
6. **The VM backend keeps running after `start.sh` exits.** Exiting stops only the console, local helpers and the SSH tunnel. The shared `vss-agent`, Phoenix and the tracking stack stay up, because several people use them. To stop them on purpose, run `.scripts/native-services.sh stop vss-agent` and `.scripts/tracking-stack.sh stop` on the VM.

## 5. VM Deployment Configuration Principles (`.env.remote`)

The untracked `.env.remote` on the VM configures volume mounts, networking and remote inference. It is a copy of the committed template `.env` (`cp .env .env.remote`, then fill in section 1). The laptop copy is `.env.local`; the VM is not expected to have one, and `.githooks/setup-worktree.sh` creates neither it nor the per-service links in a checkout that has `.env.remote` and no `.env.local`. The old name `generated.env.remote` is still read when it is the only one (if both exist, `.env.remote` wins). No script falls back to `.env`: `native-services.sh`, `rebuild-svc.sh` and `vm-ensure-docker.sh` stop with the copy command when the file is missing. Every `docker compose` call of the profile also passes `compose.unused.env` before the real file, which blanks the names that only unused services mention.

1. **App and data directories:** `VSS_APPS_DIR` and `VSS_DATA_DIR` stay blank: the VM scripts supply them for the run (`deploy/docker` of the checkout, and `<checkout>/.data`). A value you type wins.
2. **Two addresses:** `HOST_IP` is the VM's internal network IP. `vm-ensure-docker.sh` fills a blank or missing entry and updates a stale one, after a timestamped backup; the other VM scripts use the VM's address for the run when the entry is blank and leave the file alone. `EXTERNAL_IP` must be `localhost` so response URLs work over the SSH tunnel.
3. **Agent config:** `VSS_AGENT_CONFIG_FILE` must reference the `dev-profile-base` agent configuration; the shipped search configuration lacks the required `report_agent` and `video_report_gen` modules.
4. **`REPORT_REFERENCE_BASE_DIR`** must be defined (e.g. `/tmp`), or the agent crashes at startup.
5. **`STREAM_PROCESSOR_HTTP_PORT`** keeps its template default, because the service behind it (VIOS) is not deployed.
6. **Remote endpoints** are bare base URLs (no `/v1`).
7. **Client types** are `_type: openai`; the reasons for 6 and 7 are in [`architecture.md`](architecture.md#model-inference).
8. **Search embeddings** use the NVIDIA-hosted endpoint (`https://integrate.api.nvidia.com/v1/embeddings`) with `NVIDIA_API_KEY` (or `NGC_CLI_API_KEY`); the Brev key cannot call `/v1/embeddings`. The loader and the search route must use the same model (`nvidia/llama-nemotron-embed-vl-1b-v2` at 1024 dimensions).
9. **Loopback agent bind:** `VSS_AGENT_HOST` defaults to `127.0.0.1` because the agent has no authentication and holds the database admin key. Never set it to `0.0.0.0`.
10. **GPU rule: only GPU 0 is used on the VM; GPU 1 is never used, because it belongs to another user.** Every VSS Docker service and native process is pinned to GPU 0 (in `.env`, `compose.override.yml` and the script defaults). Never move a VSS workload to GPU 1, even when GPU 0 is busy.
11. **Time budget:** `INCIDENT_ANALYSIS_BUDGET_SECONDS=540`, under the console's 600 s limit, so a slow run saves its report with `image_gap` / `zoom_gap` gaps instead of timing out.
12. **Template defaults and optional blanks:** the agent config refuses to start when a setting it reads is unset, so the template gives working defaults to the eval settings; `test-env-template.sh` fails when the config gains a setting a template-built file leaves unset. `VLM_MODEL`, `VLM_GATEWAY_BASE_URL` and `VLM_GATEWAY_API_KEY` are optional blanks.

## 6. End-to-End Verification Checklist

- [ ] **Health:** `curl -s http://localhost:3200/api/health` answers 200 with `status: "ready"`; `degraded` (503) needs investigating.
- [ ] **Video ingestion:** upload an `.mp4` clip and a phone `.MOV`. Each is stored in R2 as `uploads/<original name>.mp4` (the `.MOV` converted to H.264 MP4) and plays back.
- [ ] **Report generation:** run an analysis. Type, severity, confidence, summary, entities, instruments and assets populate.
- [ ] **Persistence read-back:** the job (`GET /api/jobs`) reaches `done`, and `videos.filepath` matches the submitted R2 key.
- [ ] **Background jobs:** close the tab while a clip is Analysing, reopen `/` and confirm the Analysis jobs list shows it still running.
- [ ] **Re-generation:** re-generate with a different model and a reviewer prompt; a new AI revision appears in History and earlier revisions stay openable.
- [ ] **Human revisions:** edit a report and Save as new version, then make one revision official. Each save creates a new revision with the reviewer's name and time, and only one is official.
- [ ] **Search and filtering:** a search returns the expected incidents (it needs `evidence_crops` rows for each video's searchable revision, [what writes them](data.md#evidence_crops)), and library filters by type, severity and date range match the database.

## 7. Troubleshooting Order & Diagnostics

1. **Process status:** `./.scripts/status.sh` and `./.scripts/native-services.sh status`.
2. **Agent health:** `./.scripts/health.sh`, or `curl -s http://localhost:8000/health`.
3. **Logs:** `./.scripts/logs.sh vss-agent` for the native agent; `docker logs --tail 100 phoenix` for a container.
4. **Partial deploy:** let `start.sh` bring up the missing services, or restart one by hand with `.scripts/native-services.sh restart <svc>` or `.scripts/rebuild-svc.sh <service>` (which layers `compose.override.yml`). Do not force a redeploy over inconsistent state.
