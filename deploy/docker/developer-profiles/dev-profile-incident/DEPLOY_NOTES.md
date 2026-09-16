# Incident Console — Deploy Notes & Connection Guide

Everything fixed tonight on kwanz-ws, the current live state, and how anyone on the team connects. Written so a teammate can pick this up cold.

## How to connect (any team member)

**Settled architecture: the console (UI) runs on your own laptop; the VM runs only the backend** (vss-agent, LLM/VLM NIMs, VIOS). An SSH tunnel connects the two. This supersedes an earlier setup where the console ran as a shared container on the VM (see "Known issues" below) — follow [`incident-console/README.md`](incident-console/README.md)'s "Real backend on kwanz-ws via SSH tunnel (Phase 4)" section for the full local-console setup. Each person just needs:

1. **SSH access to kwanz-ws under your own account** (you should already have one — `yang`, `faith`, `claris`, `heng` each have their own checkout under `/home/`).
2. **A tunnel from your own laptop**, forwarding every port the stack needs (agent 8000, NIMs 30081/30082, ingress 7777) — one command, the `mdx-tunnel-incident` alias from `deploy/dotfiles/`:
   ```bash
   mdx-tunnel-incident
   ```
   It forwards all needed ports via `$VSS_VM_IP`/`$VSS_SSH_TARGET` (no hardcoded address — override those vars only if your login or the VM address differs); see its definition in `deploy/dotfiles/aliases.sh` for the underlying `ssh -N -L ...` forwards.
   Leave this running in its own terminal (it's supposed to sit there silently — that's correct, not stuck).
3. Run the console locally per `incident-console/README.md`'s Phase 4 instructions (`uv run streamlit run app.py` from `incident-console/`, pointed at the tunneled backend via `.env.local`) — each person runs their own console instance against the shared backend, not a single shared UI.

Quick health check from a second terminal, once the tunnel is up:
```bash
curl http://localhost:8000/health
# should return: {"value":{"isAlive":true}}
```

## What's actually running on the VM right now

All of these are up under `/srv/rise-up/vss/deploy/docker`, started via:
```bash
cd /srv/rise-up/vss/deploy/docker
sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <service>
```
(the root `compose.yml` in `deploy/docker` is the one to use — **not** the one inside `dev-profile-incident/`, which only defines the console app by itself)

| Container | Role | Status |
|---|---|---|
| `vss-agent` | AI agent — upload API, report generation | Up, healthy |
| `vss-incident-console` | the Streamlit UI | Up, but **superseded** — the console now runs on each person's own laptop instead (see "How to connect" above); this VM container is a leftover from the earlier shared-VM-console setup, not the path to use going forward |
| `vss-vios-streamprocessing` | video decode/encode core | Up, healthy |
| `vss-vios-nvstreamer` | upload ingestion | Up |
| `vss-vios-ingress` | nginx gateway for VST/storage API | Up, healthy |
| `vss-haproxy-ingress` | public-facing ingress on port 7777 | Up |
| `vss-vios-postgres` | VIOS's internal Postgres | Up, healthy |
| `redis` | cache | Up |
| `phoenix` | telemetry | Up |
| `vss-rtvi-embed` | embedding service | Up, healthy (search/MVP2-related, not required for MVP1 but running) |

**Not running / broken** (see "Known issues" below): `nvidia-cosmos3-reasoner` (VLM — crash-looping), `nvidia-nemotron-nano-9b-v2` (LLM — never started), `vss-vios-sensor` (sensor-ms — never started), `vss-broker-health-check` (expected to fail, MVP2/Kafka-only).

## Config fixes applied tonight (all in `generated.env.remote`, the untracked live copy)

| Setting | Was | Fixed to | Why |
|---|---|---|---|
| `VSS_APPS_DIR` | `/path/to/deploy/docker` (placeholder) | `/srv/rise-up/vss/deploy/docker` | Never filled in — broke every `include:` in the compose files |
| `VSS_DATA_DIR` | `/path/to/vss-apps-data` (placeholder) | `/srv/rise-up/vss-apps-data` | Same — needed for persistent volume mounts |
| `HOST_IP` | `<HOST_IP>` (placeholder) | `10.131.1.5` | The VM's own internal address |
| `EXTERNAL_IP` | derived from `HOST_IP` (wrong) | `localhost` | Must differ from `HOST_IP` — this is what gets embedded in URLs handed back to your browser/tunnel |
| `VSS_AGENT_CONFIG_FILE` | pointed at `dev-profile-search`'s config (zero report-gen capability) | `dev-profile-base`'s config | Search's config never had `report_agent`/`video_report_gen` wired in at all |
| `REPORT_REFERENCE_BASE_DIR` | unset (crashed startup) | `/tmp` | Agent's `eval` config schema required a valid string, even though eval isn't actually used here |
| `STREAM_PROCESSOR_HTTP_PORT` | unset → defaulted to `30001` | `10000` | nginx is hardcoded to proxy to `localhost:10000`, but the service's own default is `30001` — a pre-existing inconsistency in the repo's own shared `vst.env` |

**Compose wiring:** the actual fix was realizing commands must run from `deploy/docker` using that directory's own `compose.yml` (which already correctly includes `services/compose.yml` + `developer-profiles/compose.yml` + `industry-profiles/compose.yml`), **not** from inside `dev-profile-incident/` using its own local file.

## Known issues — NOT yet fixed, tracked as follow-up work

1. **`/analyze` won't go live even after the PR merges.** `vss-agent` deploys from NVIDIA's locked prebuilt image (`nvcr.io/nvidia/vss-core/vss-agent`) — there's no `build:` wiring anywhere to actually build the container from this repo's own code. Someone needs to add a `build:` context pointed at `services/agent/docker/Dockerfile` before the new `/analyze` code can ever run on the VM.
2. **The VLM (AI vision model) is crash-looping.** `VLM_DEVICE_ID='2'` in `generated.env.remote`, but this box only has GPUs `0` and `1`. Also `HARDWARE_PROFILE=H100` is wrong for this 2×A6000 box — should be `OTHER`. *(Coordinate with whoever last touched this config before changing it.)*
3. **`sensor-ms` container was never started.** Not blocking anything tested so far, but will break sensor management features if/when someone builds on them. Fix: `docker compose ... up -d sensor-ms`.
4. **The fix to `VSS_AGENT_CONFIG_FILE` only lives in the live untracked file**, not the tracked `.env` template in the repo (`dev-profile-incident/.env:246`) — anyone who regenerates their env from that template will silently reintroduce the original bug. Needs a real code fix.
5. **`INCIDENT_LLM_BASE_URL` points at a local mock server** that isn't running on the VM — currently harmless (nothing calls it yet), but will break the moment someone wires up the "direct LLM draft" fallback feature.

## PRs opened tonight

- **PR #33** — `feat(agent): wire up incident-console /analyze endpoint for real report generation` — https://github.com/Danwidj/video-search-and-summarization/pull/33
- **PR #34** — youfarny's parallel "mock incident analyze R2 flow" PR — https://github.com/Danwidj/video-search-and-summarization/pull/34
- **PR #35** — fix for the upload flow's content-type parsing bug (backend returns JSON as `text/plain`, client silently discarded it) — https://github.com/Danwidj/video-search-and-summarization/pull/35

This repo has no CI configured (there is no `.github/workflows/` directory), so no automated checks gate these PRs — review and merge when ready.
