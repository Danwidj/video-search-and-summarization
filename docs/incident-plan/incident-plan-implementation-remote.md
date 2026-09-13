# VSS Customization Plan — Incident Search & Reporting Capstone (Implementation — Remote LLM/VLM Deployment)

*This is the AI/implementer-facing half of the plan — exact file paths, config keys, and technical findings, written for whoever is actually building this. Decisions, rationale, and the what-ships-when narrative live in the companion document, `incident-plan-overview.md` ("the Overview doc"). Cross-references below point to it by name.*

*This file is scoped to remote (NGC-hosted) LLM/VLM deployment specifically — a self-contained reference for that path, not a comparison of alternatives. A separate local-LLM/VLM-deployment reference exists as a sibling document; this file doesn't discuss it. Everything that doesn't depend on deployment mode — Postgres, R2, the frontend app, the AI-trigger API, feature implementation, engineering evaluation, and the resulting directory tree — lives in the shared companion doc, `incident-plan-implementation-shared.md`; read this file's §1–§2 first, that one second.*

**Assumes you've read the repo root `README.md` and `deploy/docker/README.md`** — baseline `dev-profile.sh`/Compose mechanics (profile flags, `--llm-env-file`, `generated.env`, the `/v1`-suffix rule) aren't re-explained here. This doc only covers what's specific to `dev-profile-incident` or wasn't already documented there.

**This project only ever deploys via Docker Compose (`deploy/docker/`) — `deploy/helm/` is upstream NVIDIA Kubernetes tooling, not used here.** The §1 citation below points into it only as evidence for a config value, not as a deployment instruction.

**Note on scope:** this plan was originally organized around the team's epic/story numbering. Since that document is still being refined, every citation like "Story X.Y" has been replaced with a plain description of the capability itself — the technical content is unchanged, it's just no longer pinned to a numbering scheme that will drift. If a specific number/threshold below (e.g. a severity cutoff) isn't explicitly marked as sourced from the team's own spec, treat it as a reasonable default proposed here, not a confirmed requirement — check it against whatever the current epic/story doc says before building.

---

## 1. New profile setup + remote LLM/VLM + GPU topology (prerequisite for everything else)
*Terms used below: **VIOS** = VSS's Video I/O Storage service (ingestion/decode/encode); **RT-CV** = VSS's real-time computer-vision perception service (`vss-rtvi-cv`); **SDRC** = VSS's routing controller for RTSP camera registration (`sdr-controller`), the default routing mode for search/lvs/alerts profiles.*

Register the new profile: append `- path: ./dev-profile-incident/compose.yml` to `deploy/docker/developer-profiles/compose.yml`'s `include:` list (the only edit to a shared/NVIDIA-owned file this step requires — additive, one line, low conflict risk on Daniel's occasional upstream syncs). Create `deploy/docker/developer-profiles/dev-profile-incident/` with a `compose.yml` mirroring `dev-profile-search`'s shape (an `include:` for `./incident-console/compose.yml`, our own directory — see the shared doc's §3 — no need to inherit search's `kibana-init-container-search` block, we don't use Kibana).

`.env`: copy from `dev-profile-search/.env` (keep `BP_PROFILE=bp_developer_search` — this is what makes the compose-profile tag a superset, do not change it).

`config.yml`: **do not copy `dev-profile-search`'s `config.yml` and strip it down.** Verified directly: `dev-profile-search/vss-agent/configs/config.yml` has no `report_agent`/`video_report_gen` in its `functions:` block at all, and its `workflow.subagent_names` is `['search_agent']` only — it has zero report-generation capability today. Instead, build the new `config.yml` starting from `dev-profile-base`'s `functions.report_agent`, `functions.video_report_gen`, and `workflow` (with `subagent_names: ['report_agent']`) as the MVP1 baseline, then for MVP2 *append* search's `functions.search`/`search_agent`/`embed_search`/`attribute_search`/`critic_agent` and extend `workflow.subagent_names` to `['report_agent', 'search_agent']` with a hand-written combined routing prompt. **Flag:** no existing NVIDIA profile (base/search/lvs/alerts) combines two subagents in one `workflow` — this specific combination is untested in this codebase and should be smoke-tested early once MVP2 wiring happens, not assumed to work by analogy.

**LLM/VLM run remotely (NGC-hosted), not as local NIM containers.** Decided after checking actual GPU cost/benefit — running them locally would consume an entire GPU for no reason once a free-tier hosted option exists. In the new `.env`, set:
```
LLM_MODE=remote
VLM_MODE=remote
LLM_MODEL_TYPE=openai
VLM_MODEL_TYPE=openai
LLM_NAME_SLUG=none              # mandatory for remote — COMPOSE_PROFILES builds its NIM-container-selection
VLM_NAME_SLUG=none              # tag from *_NAME_SLUG; leaving the old slug would still try to resolve a
                                 # local NIM compose file that no longer matches LLM_MODE=remote's tag shape
LLM_BASE_URL=https://integrate.api.nvidia.com
VLM_BASE_URL=https://integrate.api.nvidia.com
LLM_ENDPOINT_URL=https://integrate.api.nvidia.com   # required alongside --use-remote-llm; distinct var from
VLM_ENDPOINT_URL=https://integrate.api.nvidia.com   # LLM_BASE_URL/VLM_BASE_URL above, both are needed
NVIDIA_API_KEY=<your key>       # never commit this — keep it in generated.env (gitignored) or a local-only env file
OPENAI_API_KEY=<same key as NVIDIA_API_KEY>   # see "Auth gotcha" below — this is not optional
```
Base URL confirmed in-repo (not guessed): identical value in `deploy/helm/developer-profiles/dev-profile-search/values-build-endpoint.yaml` and the `vss-deploy-profile` skill's `references/env-overrides.md`.

**`/v1` suffixing:** standard VSS behavior, documented in `deploy/docker/README.md`'s LVS section — don't include `/v1` in `LLM_BASE_URL`/`VLM_BASE_URL`. One exception specific to this build: the `openai_vlm` bug below requires adding it explicitly in `config.yml`.

**Auth gotcha — confirmed, not hypothetical:** VSS's `openai`-type LLM/VLM client blocks in `config.yml` authenticate by reading the standard `OPENAI_API_KEY` environment variable, **not** `NVIDIA_API_KEY` — even when the configured endpoint is NVIDIA's own (`integrate.api.nvidia.com`). Setting only `NVIDIA_API_KEY` (as the plan originally specified) produces **silent 401s with no obvious cause** — the request looks correctly formed, the endpoint is right, but auth fails. Fix: set `OPENAI_API_KEY` to the same value as `NVIDIA_API_KEY` in the `.env`, as shown above.

**Real code bug — already patched locally, but not upstream in NVIDIA's repo, so don't assume it's fixed after a fresh clone or sync.** The `openai_vlm` client block in `vss-agent/configs/config.yml` (and `config_rag.yml`) originally shipped missing a `base_url` line — every sibling block (`nim_llm`, `nim_vlm`, `openai_llm`) has one, `openai_vlm` didn't. Left as-is, VLM calls silently go to the real public OpenAI API instead of the configured NVIDIA endpoint — a genuinely dangerous failure mode (wrong provider entirely, not just a wrong URL, and it fails silently rather than erroring). **Current status: already fixed as an uncommitted local edit** — `dev-profile-base/vss-agent/configs/config.yml:204` and `config_rag.yml:210` both now have `base_url: ${VLM_BASE_URL}/v1` (confirmed present, checked directly against the files). Since `dev-profile-incident`'s config is built from `dev-profile-base`'s (§1 above), this fix carries over automatically as long as it's copied *after* this local patch, not from a fresh upstream sync. **If re-syncing from NVIDIA's upstream repo, re-apply this patch first** — add `base_url: ${VLM_BASE_URL}/v1` to the `openai_vlm` block in both files. Note this is the one place the `/v1` suffix is added explicitly rather than relying on VSS's automatic appending — this specific code path doesn't auto-append it.

**Flag — model ID needs verification before relying on it, don't just carry the local choice forward.** The plan's earlier local-NIM framing picked `nemotron-3-nano` specifically because it's a small model, chosen to leave VRAM headroom for a VLM sharing the same GPU under local hosting. That constraint doesn't apply under remote mode — but it also means `nemotron-3-nano` was never actually confirmed to exist as an NGC-hosted **remote** catalog entry (the one in-repo reference for remote mode, `values-build-endpoint.yaml`, uses `nvidia/nvidia-nemotron-nano-9b-v2` instead — a different model directory in `deploy/docker/services/nim/`). There's now no reason *not* to pick a stronger remote model if a probe confirms it's available.

**Probing is not a one-time pre-deploy check — re-run it before every deploy.** Two separate, confirmed failure modes make this necessary:
- **Catalog listing ≠ invocation access.** A model can appear in `/v1/models` and still return `404 Function not found for account` when actually called. Listing the catalog is not sufficient evidence a model is usable — always probe with a real request against the exact `LLM_NAME`/`VLM_NAME` you intend to deploy.
- **Models get deprecated with no warning** (`410 Gone` — EOL). A model confirmed working in one session can be dead in the next.

Run `scripts/probe_remote_models.sh` (documented in the `vss-deploy-profile` skill's `references/credentials.md#remote-endpoint-probes`) against whichever `LLM_NAME`/`VLM_NAME` you're using, **immediately before every deploy**, not just once at project start.

**No `HARDWARE_PROFILE`/`hw-*.env` NIM sizing needed** — that mechanism exists solely to right-size a *local* NIM container's VRAM fraction, which doesn't apply once nothing NIM-related runs on this VM. The shared doc's §7 directory tree reflects this — no `hw-OTHER.env` entry.

**Structural ceiling — the real reason to think twice about remote for anything beyond light dev use.** NVIDIA's free hosted tier caps concurrent requests at **16**. VSS's report-generation feature fires many parallel frame-analysis calls per video, which saturates that ceiling — and, critically, the pipeline **loops indefinitely rather than degrading gracefully** when this happens (no clean backoff or error surfaced, it just hangs). Reducing `max_frames` in `vss-agent`'s config reduces the chance of hitting this but does not eliminate it. **There is no reliable self-service way to raise this limit.**
**Flag — open, pending:** someone is currently researching whether a genuinely better remote option exists — a different NVIDIA program, a self-hosted OpenAI-compatible endpoint, or another provider entirely. Treat the 16-concurrent-request ceiling as this deployment path's binding constraint until that research lands; revisit this section once it does.

**GPU device topology (remote mode).** With LLM/VLM off the GPU entirely, only VIOS's own video pipeline and MVP2's search-perception services touch the GPU at all:

| GPU | Services | Why |
|---|---|---|
| **GPU 0** | `vss-vios-nvstreamer` (upload ingestion — hardcoded `device_ids: ["0"]`, `video-analytics-2d-app/compose.yml:63-64`, MVP1) + `vss-vios-streamprocessing` (VIOS core decode/encode — `runtime: nvidia`, no device pin, `deploy/docker/services/vios/streamprocessing/docker-compose.yaml:22,71,121,173`, MVP1) + `vss-rtvi-cv` (RT-CV/DeepStream perception, MVP2 only) + RT-Embed (video-embedding generation, MVP2 only, **default placement** — see below) | Nothing running locally under remote mode is VRAM-heavy (LLM/VLM-scale) — consolidating onto one card is reasonable. |
| **GPU 1** | Idle by default | Free to repurpose (a teammate, other coursework) or leave idle. |

**MVP1: only GPU 0 is used at all** — `vss-vios-nvstreamer` and `vss-vios-streamprocessing`. GPU 1 is completely free.

**MVP2: still 1 GPU by default** — RT-CV and RT-Embed both land on GPU 0 alongside ingestion/codec (`RT_CV_DEVICE_ID='0'`, `RT_EMBED_DEVICE_ID='0'`). This is a reasonable consolidation since nothing here is VRAM-heavy, but it does introduce the one real contention risk in this deployment path: RT-CV (real-time, latency-sensitive) and RT-Embed sharing SM/decode engines with ingestion and codec work simultaneously. **Optional fallback if that contention actually shows up under real MVP2 load:** split RT-Embed onto GPU 1 alone (`RT_EMBED_DEVICE_ID='1'`) — isolates the workload most likely to cause it. Not decided here; revisit once actually sizing/testing MVP2.

`LLM_DEVICE_ID`/`VLM_DEVICE_ID` can be left in `.env` unedited (harmless, just unused under remote mode) rather than cleaned up.

---

## 2. Docker + Local Dev Guide

**Backend on the VM** (standard flow from the `vss-deploy-profile` skill, targeting the new `dev-profile-incident`):
```bash
cp deploy/docker/developer-profiles/dev-profile-incident/.env deploy/docker/developer-profiles/dev-profile-incident/generated.env.remote
docker compose --env-file generated.env.remote config > resolved.yml
# MVP1: bring up only the base-equivalent containers by name (vss-agent-ui excluded — Streamlit is the default UI, see the Overview doc's Context)
docker compose --env-file generated.env.remote -f resolved.yml up -d vss-agent incident-console <vios-containers> redis phoenix
# MVP2: bring up everything else already tagged bp_developer_search_2d — RT-CV (vss-rtvi-cv), the search embedding/indexing
# pipeline (vss-behavior-analytics, vss-video-analytics-api — NOT generic analytics, this IS the search pipeline in this
# profile, see the Overview doc §2 MVP1/MVP2 Summary), Elasticsearch/Logstash/Kibana, Kafka, SDRC (routing controller)
docker compose --env-file generated.env.remote -f resolved.yml up -d
```
No `<nemotron-3-nano container>` in the MVP1 up-list — remote mode has no local NIM container to start.

**Where the real values go (G8):** after the `cp`, edit the real values into the
ignored `generated.env.remote` copy itself (or export them in the deploy shell) —
`INCIDENT_DB_DSN`, the four `R2_*` keys, `NGC_CLI_API_KEY` / `NVIDIA_API_KEY` /
`OPENAI_API_KEY`, the LLM/VLM endpoint URLs, plus the hand-maintained machine values
(`HOST_IP`, `EXTERNAL_IP`, `VSS_*`). The tracked `.env` stays placeholders; never
create `incident-console/.env.local` on the VM — nothing on the deploy path reads it,
and `COPY . .` would bake it into the image. **G9:** `dev-profile.sh` accepts no
`incident` profile, so this `generated.env.remote` is hand-made and bypasses the
script's machine resolution — the operator must ensure `HOST_IP`/`VSS_*`/`NGC_*` by hand.

**Maintain a dedicated `generated.env.remote` file, always invoked explicitly with `--env-file`.** `dev-profile.sh up` writes to a shared CLI `.env` template rather than a clean, isolated per-deploy file — if this deployment is ever switched to/from local mode on the same profile, values (routing type, base URLs) can go stale unless every relevant var is explicitly re-passed each time. Using a dedicated, explicitly-named env file sidesteps this — everything needed for remote mode lives in one self-contained file, nothing carried over implicitly.

**Never run `dev-profile.sh down`.** It runs `docker compose down -v` and then deletes the entire data directory. Use plain `docker compose down` (no `-v`) instead. (Less catastrophic under remote mode specifically, since there's no local model-weight cache to lose — but other cached/working state is still deleted, so the rule holds regardless of LLM/VLM mode.)

**Startup timing:** expect real cold-start time even without local NIM containers to build — VIOS and the rest of the stack still need to come up. A 503 during the startup window is expected, not necessarily a bug; check `docker ps -a` before assuming something's broken. **Flag:** the commonly-cited ~6–7 minute cold-start figure was measured for local mode (which includes NIM container builds) — remote mode's actual cold-start time is likely shorter but hasn't been separately measured; don't assume the same figure applies here.

**New incident-console app locally — no Docker, no GPU.** `incident-console/` is its own `uv`-managed Python package (`pyproject.toml` + `uv.lock`, same convention as `services/agent`), not a container, for local dev — Docker bind-mount hot reload has more overhead than just running the process natively:
```bash
cd dev-profile-incident/incident-console
uv sync
uv run streamlit run app.py
```
This gets native hot reload (Streamlit's own `runOnSave`, no container involved) and needs nothing GPU-backed to run most of the app:
- **Postgres:** point `INCIDENT_DB_DSN` at the real Hyperdrive-backed instance directly — no local Postgres, no fixture-seeding to maintain. Catalog, metadata edits, report edit/verify, notifications, dashboard, and eval-log all go straight to it and have zero GPU dependency by design (the shared doc's §3, "direct Postgres, not REST" decision). The only care needed: this is shared state across the team, so use an obvious convention for anything you insert yourself (e.g. a `test-` prefix) rather than editing real rows.
- **The two AI-trigger endpoints (shared doc §4)**, the only remote-endpoint-touching part of the app: don't require a real Elasticsearch to exercise. Both `report_agent` and `search_agent` talk to their LLM/VLM over a plain OpenAI-compatible `/v1/chat/completions` `base_url` (confirmed — every `llms:` entry in `dev-profile-base/vss-agent/configs/config.yml` is `_type: nim` or `_type: openai` hitting a `base_url` this way). So: run the *real* `vss-agent` locally too (per "Agent code locally" below), but point its `LLM_BASE_URL`/`VLM_BASE_URL` at a small local mock server instead of the real remote endpoint — a tiny FastAPI/Uvicorn app implementing `POST /v1/chat/completions` and returning a canned completion shaped like `IncidentReport`, its own small `uv`-managed package (or folded into `incident-console`'s), run the same way: `uv run uvicorn mock_llm_server:app --port <LLM_PORT>`. This exercises the *real* route → tool-calling → schema-extraction → Postgres-write path with zero real API calls (avoiding both the rate-limit ceiling and burning real quota during iteration) and zero Elasticsearch. (A simpler fallback — mocking the two endpoints directly instead of the LLM — is less code but only useful for pure frontend-shape iteration once the response contracts are stable, since it bypasses `vss-agent`'s own logic entirely.)
- **Video playback:** `st.video(url)` points straight at an R2 URL once a video exists there — no VIOS/NvStreamer/agent involvement for playback (only upload goes through the agent's contract). Point at real test-fixture R2 videos; no backend needs to be running for this at all.

Reachable over the Tailscale hostname when pointing at the real VM-hosted `vss-agent` instead of a local one.

**Existing UI locally (optional, if still wanted for chat/search demos):**
1. `docker compose ... up -d --scale vss-ui=0`
2. `cd services/ui && npm install && npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui`
3. Point `NEXT_PUBLIC_*` vars at `http://<tailscale-host>:<HAPROXY_PORT>/...`

**Agent code locally:** `services/agent` is a normal uv-managed Python package — run locally against the VM's exposed remote-LLM config/VIOS/Postgres, or `docker compose up -d --build vss-agent` on the VM for a fast single-container rebuild.

**VIOS:** no dev-server mode — rebuild image + `docker compose up -d --force-recreate <vios-service>` on the VM.

---

## 3. Reference: NVIDIA Stock Profile Configs (base/search — not `dev-profile-incident`)

Verified/derived configs for running NVIDIA's own `base`/`search` profiles directly under remote LLM/VLM mode. Copy-paste commands live in the Overview doc, §1.3. **This is reference material only — not part of the `dev-profile-incident` build**, kept here because it's directly relevant prior art for §1.

### Base — remote (chat verified working; report generation not re-tested on this exact config)

```
export LLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export VLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export OPENAI_API_KEY="$NVIDIA_API_KEY"
```
Command uses `--host-ip 10.131.1.5 --external-ip localhost`, not `--host-ip localhost` — see the command in the Overview doc, §1.3.

**Real bug, flagged after the fact.** `VST_INTERNAL_URL` is the URL `vss-agent` uses to fetch an uploaded video from VIOS during report generation — confirmed set in `.env` as `VST_INTERNAL_URL=http://${HOST_IP}:${VST_PORT}`, i.e. it's derived automatically from whatever `--host-ip` resolves to, not something you set separately. The original version of this command used `--host-ip localhost`, and was marked "verified working" based on chat working correctly under it. Chat doesn't need `vss-agent` to fetch the video file itself, so it never exercised this path — with `--host-ip localhost`, `VST_INTERNAL_URL` becomes `http://localhost:${VST_PORT}`, which resolves to the `vss-agent` container itself, not the VIOS container serving the video, so the fetch fails. We only discovered this while testing the dedicated-GPU local setup, and it's about container-to-container video fetch during report generation, **unrelated to where the LLM/VLM run** — so it applies here too, and `--host-ip localhost` is wrong for the same reason it was wrong elsewhere. The command above is corrected to the same `--host-ip`/`--external-ip` split used everywhere else, but **report generation has not actually been re-run against this corrected config** — only chat was ever confirmed working, and that was under the old (wrong) `--host-ip`. Treat report generation on remote Base as unverified until it's explicitly re-tested.

Confirms §1's auth-gotcha finding directly: `OPENAI_API_KEY` reads that variable name for auth even when calling NVIDIA's own endpoint.

**Only `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` is confirmed callable on the free tier as of this session** (used for both LLM and VLM roles here) — other listed models 404'd. One concrete confirmed-working data point for §1's "model needs verification" flag, though not necessarily the final pick for `dev-profile-incident`.

**Why this isn't the recommended primary path:** confirms §1's structural-ceiling finding exactly — this config loops on longer videos for the reason described there.

### Search — remote (derived from VSS docs, not yet tested)

`dev-profile-search/generated.env` (search-only settings — no CLI flag exists for these; LLM/VLM mode and model are set via the command below instead, same as Base — remote):
```
RT_CV_DEVICE_ID=0          # dedicated GPU, full perception throughput, no co-resident VLM
RT_EMBED_DEVICE_ID=1       # dedicated GPU, up to ~30 streams
NUM_STREAMS=16
```
```bash
export LLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export VLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export OPENAI_API_KEY="$NVIDIA_API_KEY"

./deploy/docker/scripts/dev-profile.sh up --profile search --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --use-remote-llm --llm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning \
  --use-remote-vlm --vlm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning
```
No `--llm-device-id`/`--vlm-device-id` needed under `--use-remote-llm`/`--use-remote-vlm` — remote mode has no local container to pin.

**RT-CV and RT-Embed can never go remote** — perception and embedding are always local GPU inference in VSS, regardless of LLM/VLM placement. Upside: full perception throughput, since nothing shares GPU 0 anymore once LLM/VLM go remote. Same 16-concurrent-request ceiling on the LLM/VLM side as Base — remote above.
