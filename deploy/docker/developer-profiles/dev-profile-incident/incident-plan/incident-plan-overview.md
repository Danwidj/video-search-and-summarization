# Incident Search & Reporting Capstone — Overview

## 1. What this is

Video-driven incident search and reporting built on this VSS blueprint fork. A Streamlit console (`incident-console`) sits on Postgres (reports) + R2 (video), triggers report generation and search through `vss-agent`, and runs inside a new `dev-profile-incident` deployment profile.

## 2. Where things live

- Plan docs: this directory (`deploy/docker/developer-profiles/dev-profile-incident/incident-plan/`; this file; `incident-plan-implementation-local.md` / `-remote.md` for mode-specific setup; `incident-plan-implementation-shared.md` for mode-independent build).
- Profile: `deploy/docker/developer-profiles/dev-profile-incident/` (`compose.yml`, `incident-console/`, `mock-backend/`).
- Console schema, authoritative: `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py` (module docstring + `incident-console/README.md`).
- GPU-less UI loop: `mock-backend/base_profile_mock/README.md`.
- `origin` is the team fork; `upstream` is NVIDIA's repo.

## 3. Environments and access

- `kwanz-ws`: 2x RTX A6000 (48 GB each), Threadripper PRO 5975WX, 251 GiB RAM, 1.8 TB NVMe. Tailscale: `kwanz-ws.tailf3aa43.ts.net`.
- VM checkout: `/srv/rise-up/vss`. NGC credentials: `/srv/rise-up/.ngc_env` (`set -a; source /srv/rise-up/.ngc_env; set +a`).
- Reach the UI: `ssh -N -L 7777:10.131.1.5:7777 daniel@kwanz-ws`, browse `http://localhost:7777`.
- Deploy flags used everywhere on this host: `--host-ip 10.131.1.5 --external-ip localhost --hardware-profile OTHER`.

## 4. How to run

Stock `base`, local LLM/VLM (verified working; tuning lives in each model's `deploy/docker/services/nim/<model>/hw-OTHER.env`, no override flags):

```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a
./deploy/docker/scripts/dev-profile.sh up --profile base --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 --llm-device-id 0 \
  --vlm nvidia/cosmos3-reasoner --vlm-device-id 1
```

Stock `base`, remote LLM/VLM (verified working; model `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` for both roles):

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

- `--llm-model-type`/`--vlm-model-type` are `openai`, not `nim`. `nim`-type is non-functional (upstream `nvidia-nat` bug: `nim_langchain` leaks `verify_ssl` into the request body; issue #1894 / PR #1862, unmerged as of 2026-09-06).
- `dev-profile-incident` deploys via `docker compose --env-file generated.env.<local|remote>` (see the mode doc §2). Never run `dev-profile.sh down` (deletes the data dir incl. ~35 GB cached weights); use plain `docker compose down`.
- Local UI iteration needs no GPU/VM: `cd deploy/docker/developer-profiles/dev-profile-incident/incident-console && uv sync && uv run streamlit run app.py` (see `incident-console/README.md`'s local dev loop).

## 5. Current status (as of 2026-09-21)

### 5.1 Feature / verification status

| Item | State |
|---|---|
| `incident-console` app (catalog, report review, dashboard, human-eval; Postgres-backed, no offline mode) | Present; seed via `incident-console/scripts/seed_supabase.py` over `fixtures/data/*.csv` |
| Console schema (`db.py`: videos/queries/model_runs/incidents + evidence, ground-truth, match, review tables) | Present; authoritative for schema questions |
| Mock backend + local loop (`mock-backend/base_profile_mock`) | Present; verified loop documented |
| Stock base-local deploy (one model per GPU, `hw-OTHER.env` sizing) | Verified working |
| Stock base-remote chat + VLM describe (`openai`-type, model above) | Verified working 2026-09-13 on corrected `--host-ip`: video upload to VST plus `video_understanding` through the remote VLM returned a correct description. Full `report_agent` path still needs a UI websocket (HITL), so it remains unverified headless. |
| Stock `search` profile (local and remote) | Verified working 2026-09-13 both modes; deploy commands in the mode docs §3 |
| `incident_report_gen` tool + `/analyze` API route | Built (PR #38, merged 2026-09-17); fresh deploy builds from source via `start.sh`'s `--build` (PR #63), and `vss-agent` runs natively on kwanz-ws (PR #70). Confirm the VM's active `vss-agent` process was restarted or redeployed since PR #63/#70 |
| Supabase / PostgREST integration | Migration validated against live project (PR #53); agent-side client ported from asyncpg to `supabase-py` PostgREST (PR #54, #57); `INCIDENT_SUPABASE_URL` and `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` wired to agent (PR #62) for port-5432-safe access on kwanz-ws |
| Tier 1 ground-truth evaluation | Built (PR #56, merged 2026-09-20); scores model runs against parallel `gt_*` tables via `eval_gt.py` / report detail UI |
| `dev-profile-incident` `config.yml`, `/search` API route | Planned (shared doc §§4-6); not yet built |
| `openai_vlm` missing-`base_url` patch (`base_url: ${VLM_BASE_URL}/v1` in `config.yml` + `config_rag.yml`) | Required; re-apply after any upstream sync |
| Remote free-tier 16-concurrent-request ceiling; hosted-model 12-images-per-prompt cap | Open constraints; remote report path loops/hangs past them |

### 5.2 Live deployment on kwanz-ws

The profile's backend (`vss-agent`, LLM/VLM NIMs, VIOS) runs on the shared `kwanz-ws` VM. **The `incident-console` UI runs on each team member's own laptop, not on the VM** - an SSH tunnel connects the two. This supersedes an earlier setup where the console ran as a shared container on the VM.

Docker appliance containers are up under `/srv/rise-up/vss/deploy/docker`, started via:

```bash
cd /srv/rise-up/vss/deploy/docker
sudo docker compose -f compose.yml --env-file developer-profiles/dev-profile-incident/generated.env.remote up -d <service>
```

(the root `compose.yml` in `deploy/docker` is the one to use - **not** the one inside `dev-profile-incident/`, which only defines the console app by itself)

`vss-agent` itself is **not** one of these containers — it runs natively via `scripts/native-services.sh` (see `dev-profile-incident/README.md`'s "Native vs. Docker service split").

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

### 5.3 Known issues

1. ~~**`vss-agent` now builds from source, but the VM hasn't redeployed yet.**
   `deploy/docker/services/agent/compose.yml`'s `vss-agent` service now carries
   a `build:` context (`services/agent/docker/Dockerfile`, context `services/`)
   alongside its `image:` tag, so `docker compose up -d --build vss-agent`
   rebuilds the container from this repo's own code (e.g. the `/analyze` route)
   instead of NVIDIA's locked prebuilt image. A plain `up -d` — no `--build` —
   still reuses whatever image already exists locally. What's currently running
   on the VM is still the prebuilt image; run one `--build` deploy there before
   relying on any agent-side code change.~~ **FIXED** — `start.sh` now passes `--build` on fresh deploys (PR #63), and `vss-agent` now runs natively on kwanz-ws from source (PR #70). Confirm the VM process/container was restarted after PR #63/#70.
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

## 6. Scope

MVP1 (no natural-language search):

- Video catalog, upload, metadata editing, retention.
- Report generation with structured fields (description, persons, classification, severity, confidence, start/end timestamps).
- One-click pipeline trigger, status transitions, high-severity notifications.
- Console UI except the search box; human-eval flow + report-quality scoring.

MVP2 (adds):

- Natural-language search (RT-CV + RT-Embed + Elasticsearch stack; `search_agent`/`embed_search` wired into `config.yml`).
- Retrieval precision/recall/F1 evaluation.

Standing facts: profile reuses the `bp_developer_search` compose tag; `config.yml` starts from base's `report_agent`/`video_report_gen` and appends search functions at MVP2; pipeline orchestration extends `vss-agent` tool-calling; R2 is the canonical video store, Postgres the canonical report store, local VIOS disk a working cache; `edited_by`/`verified_by`/`rater` are freeform text, no accounts.

## 7. Verification checklist

- Upload a clip: appears in the catalog with correct status/count; lands in R2 and is retrievable.
- Generate a report: every structured field populates; ambiguous input degrades (empty persons, unconfirmed start time).
- Edit metadata, regenerate: the new report reflects the edit.
- Full-pipeline trigger: status moves through its lifecycle incl. an induced failure surfacing in the UI.
- Verify a report: status flips; severity >= 4 raises a notification (default threshold, unconfirmed).
- Search/filter, timestamp-jump, dashboard charts: reflect real rows; clearing filters returns the full set.
- Human-eval sample: agreement rate matches a hand-computed value.
