# VSS Customization Plan — Incident Search & Reporting Capstone (Implementation — Local LLM/VLM Deployment)

*This is the AI/implementer-facing half of the plan — exact file paths, config keys, and technical findings, written for whoever is actually building this. Decisions, rationale, and the what-ships-when narrative live in the companion document, `incident-plan-overview.md` ("the Overview doc"). Cross-references below point to it by name.*

*This file is scoped to local LLM/VLM deployment specifically — LLM and VLM run as local NIM containers on this VM's own GPUs, not against a hosted endpoint. A separate file, `incident-plan-implementation-remote.md`, covers the remote-hosted alternative; the two are not meant to be read together, pick whichever matches how you're actually deploying. Everything that doesn't depend on deployment mode — Postgres, R2, the frontend app, the AI-trigger API, feature implementation, engineering evaluation, and the resulting directory tree — lives in the shared companion doc, `incident-plan-implementation-shared.md`; read this file's §1–§2 first, that one second.*

**Assumes you've read the repo root `README.md` and `deploy/docker/README.md`** — baseline `dev-profile.sh`/Compose mechanics (profile flags, `--llm-env-file`, `generated.env`, the `/v1`-suffix rule) aren't re-explained here. This doc only covers what's specific to `dev-profile-incident` or wasn't already documented there.

**Note on scope:** this plan was originally organized around the team's epic/story numbering. Since that document is still being refined, every citation like "Story X.Y" has been replaced with a plain description of the capability itself — the technical content is unchanged, it's just no longer pinned to a numbering scheme that will drift. If a specific number/threshold below (e.g. a severity cutoff) isn't explicitly marked as sourced from the team's own spec, treat it as a reasonable default proposed here, not a confirmed requirement — check it against whatever the current epic/story doc says before building.

---

## 1. New profile setup + local LLM/VLM + GPU topology (prerequisite for everything else)
*Terms used below: **VIOS** = VSS's Video I/O Storage service (ingestion/decode/encode); **RT-CV** = VSS's real-time computer-vision perception service (`vss-rtvi-cv`); **SDRC** = VSS's routing controller for RTSP camera registration (`sdr-controller`), the default routing mode for search/lvs/alerts profiles.*

Register the new profile: append `- path: ./dev-profile-incident/compose.yml` to `deploy/docker/developer-profiles/compose.yml`'s `include:` list (the only edit to a shared/NVIDIA-owned file this step requires — additive, one line, low conflict risk on Daniel's occasional upstream syncs). Create `deploy/docker/developer-profiles/dev-profile-incident/` with a `compose.yml` mirroring `dev-profile-search`'s shape (an `include:` for `./incident-console/compose.yml`, our own directory — see the shared doc's §3 — no need to inherit search's `kibana-init-container-search` block, we don't use Kibana).

`.env`: copy from `dev-profile-search/.env` (keep `BP_PROFILE=bp_developer_search` — this is what makes the compose-profile tag a superset, do not change it).

`config.yml`: **do not copy `dev-profile-search`'s `config.yml` and strip it down.** Verified directly: `dev-profile-search/vss-agent/configs/config.yml` has no `report_agent`/`video_report_gen` in its `functions:` block at all, and its `workflow.subagent_names` is `['search_agent']` only — it has zero report-generation capability today. Instead, build the new `config.yml` starting from `dev-profile-base`'s `functions.report_agent`, `functions.video_report_gen`, and `workflow` (with `subagent_names: ['report_agent']`) as the MVP1 baseline, then for MVP2 *append* search's `functions.search`/`search_agent`/`embed_search`/`attribute_search`/`critic_agent` and extend `workflow.subagent_names` to `['report_agent', 'search_agent']` with a hand-written combined routing prompt. **Flag:** no existing NVIDIA profile (base/search/lvs/alerts) combines two subagents in one `workflow` — this specific combination is untested in this codebase and should be smoke-tested early once MVP2 wiring happens, not assumed to work by analogy.

**LLM/VLM run as local NIM containers on this VM's own GPUs.** In the new `.env`, set:
```
LLM_MODE=local_shared
VLM_MODE=local_shared
LLM_MODEL_TYPE=nim
VLM_MODEL_TYPE=nim
LLM_NAME=nvidia/nemotron-3-nano
LLM_NAME_SLUG=nemotron-3-nano
VLM_NAME=nvidia/cosmos3-reasoner
VLM_NAME_SLUG=cosmos3-reasoner
```
No rate limiting — every request is local, no dependency on a hosted endpoint's availability or concurrency ceiling. Trade-offs: first-run NIM container build/download takes real time (minutes) and local disk space; model choice is constrained to something VRAM-modest enough to comfortably share a GPU with the VLM (and, at MVP2, potentially RT-Embed too) — `nemotron-3-nano` was picked specifically for this reason, not for capability. If VRAM headroom turns out to be more generous than expected once actually tested, revisit whether a stronger model is viable.

**Flag — GPU placement for local_shared is an unresolved, untested topology risk, not a settled decision.** The `.env` values above use `local_shared` mode, which — per `dev-profile-search/.env`'s stock default — puts LLM and VLM together sharing one GPU (see topology below). However: **NVIDIA's own documentation reportedly recommends one model per GPU for 2+-GPU hosts** (`--llm-device-id 0 --vlm-device-id 1`, i.e. NOT `local_shared`) — a teammate's field report describes a default config that crammed both LLM and VLM onto GPU 0 while GPU 1 sat idle, causing repeated crashes. This directly conflicts with the `local_shared`/shared-GPU assumption baked into this plan so far. **Do not treat the GPU topology in this section as safe until it's actually been tested on this hardware.** If `local_shared` proves unstable, the fallback is `LLM_MODE=local`/`VLM_MODE=local` with explicit, separate `--llm-device-id`/`--vlm-device-id` values — but that then raises the downstream question below.

**Downstream conflict this creates at MVP2, also unresolved:** with only 2 GPUs total, and LLM + VLM + RT-CV + RT-Embed all wanting GPU access, a strict one-model-per-GPU rule for LLM/VLM leaves no obviously-safe placement for RT-CV/RT-Embed without *something* sharing a card. Don't assume the pairing below (RT-CV alone on GPU 0, LLM+VLM+RT-Embed sharing GPU 1) is safe just because it mirrors the stock profile — the stock profile's own default already appears to be the one that caused crashes per the field report above. **This needs real testing/decision before MVP2 is built, not an assumed-safe pairing by analogy.**

**`hw-OTHER.env` sizing is required for local deployment** (this resolves what looked like a stale directory-tree entry in an earlier draft of this plan — it's not stale, it's required specifically because this is the local-deployment path). The A6000 isn't one of NVIDIA's explicitly-tested classes (H100/L40S/RTX PRO 6000 Blackwell/DGX Spark) — the shipped `hw-OTHER.env` tuning files ship completely empty, no memory-safety defaults at all. Fix: borrow the nearest tested-equivalent card's (L40S — same 48GB VRAM class) **dedicated-mode** (not shared-mode) values via `--llm-env-file`/`--vlm-env-file`:
- **LLM:** `NIM_KVCACHE_PERCENT=0.8`, `NIM_GPU_MEM_FRACTION=0.8`, `NIM_MAX_MODEL_LEN=128000`, `NIM_MAX_NUM_SEQS=4`, plus a `NIM_LOW_MEMORY_MODE`-type flag. **Flag — incomplete:** the exact value for this last flag wasn't captured in the source field notes; confirm it before relying on this list as complete.
- **VLM:** `NIM_KVCACHE_PERCENT=0.8`, `NIM_GPU_MEMORY_UTILIZATION=0.8`, `NIM_MAX_MODEL_LEN=32768`, `NIM_MAX_NUM_SEQS=4`, plus additional values not fully captured ("plus a couple" per the source field notes). **Flag — incomplete:** treat this list as a starting point, not the full set, until confirmed against the actual NIM container's accepted env vars.

Note also: the sizing values above are described as "dedicated-mode" values in the source field notes — if the GPU-placement flag above resolves toward `local_shared` (shared-mode) rather than dedicated `local`, double-check whether these same values are still appropriate, since the field notes explicitly distinguish dedicated-mode from shared-mode tuning.

**GPU device topology.** `dev-profile-search/.env:43-48` currently holds this 2-GPU split — **but check this is `dev-profile-search`'s committed upstream default before relying on it**: `git diff` on this VM shows `.env` has an uncommitted local edit changing `VLM_DEVICE_ID` from the committed default `'2'` to `'1'` (and `LLM_NAME`/`LLM_NAME_SLUG` from `nvidia-nemotron-nano-9b-v2` to `nemotron-3-nano`). The values below reflect this VM's current working copy, not necessarily what a fresh clone of `dev-profile-search` would ship with:
```
RESERVED_DEVICE_IDS='0'        # GPU 0 — dedicated, not shared
FIXED_SHARED_DEVICE_IDS='1'    # GPU 1 — shared by multiple services
RT_CV_DEVICE_ID='0'
RT_EMBED_DEVICE_ID='1'
LLM_DEVICE_ID='1'
VLM_DEVICE_ID='1'
```

| GPU | Services | Why (as documented — see the untested-topology flag above) |
|---|---|---|
| **GPU 0 — dedicated** | `vss-rtvi-cv` (RT-CV/DeepStream perception, MVP2) + `vss-vios-nvstreamer` (upload ingestion — hardcoded `device_ids: ["0"]`, `video-analytics-2d-app/compose.yml:63-64`, MVP1) | Both want predictable, low-latency access — real-time perception and hardware video transcode shouldn't contend for VRAM/SM time. |
| **GPU 1 — shared** | LLM NIM + VLM NIM (MVP1 onward), joined by RT-Embed at MVP2 | Small/VRAM-modest models chosen specifically to fit together on one 48GB card — **but see the flag above: this exact sharing pattern is what reportedly caused crashes in a teammate's deployment. Do not treat as safe until tested on this hardware.** |
| **Either (no pin)** | `vss-vios-streamprocessing` (VIOS's core decode/encode, MVP1) — `runtime: nvidia`, no `NVIDIA_VISIBLE_DEVICES` set, `deploy/docker/services/vios/streamprocessing/docker-compose.yaml:22,71,121,173` | Hardware codec work, not model inference — doesn't meaningfully compete for VRAM on whichever card it lands on. |

### MVP1 — which services actually run

| Service | GPU | Notes |
|---|---|---|
| `vss-vios-nvstreamer` (upload ingestion) | GPU 0 | hardcoded `device_ids: ["0"]`, not env-configurable |
| `vss-vios-streamprocessing` (VIOS core decode/encode) | GPU 0 (unpinned, typically) | hardware codec, doesn't meaningfully contend for VRAM |
| LLM NIM + VLM NIM | GPU 1 (shared) | see untested-topology flag above |
| RT-CV, RT-Embed | — | not running yet (MVP2 only) |

**MVP1 net GPU usage: both GPUs in use** — GPU 0 for ingestion/codec, GPU 1 for LLM+VLM.

### MVP2 — adds RT-CV + RT-Embed

| Service | GPU | Notes |
|---|---|---|
| RT-CV (`vss-rtvi-cv`, real-time perception) | GPU 0 (`RT_CV_DEVICE_ID='0'`) | wants predictable low-latency access, shouldn't contend with LLM/VLM/RT-Embed |
| RT-Embed (video-embedding generation) | GPU 1 (`RT_EMBED_DEVICE_ID='1'`) | joins LLM NIM + VLM NIM already there — now a 3-way shared card |
| LLM NIM + VLM NIM | GPU 1 (unchanged from MVP1) | |

**At MVP2, GPU 1 becomes a 3-way share (LLM + VLM + RT-Embed), all intended to be VRAM-modest.** This is the fullest exercise of the stock reference topology — and also the point where the untested-topology risk flagged above matters most, since it's the most crowded single card in the whole plan. Smoke-test this specifically before relying on it for a real MVP2 demo.

### Additional local-deployment operational gotchas

These came from a teammate's field notes and aren't otherwise documented anywhere in this plan or the codebase:

- **`--host-ip` vs `--external-ip`.** `--host-ip` must be the VM's real LAN IP — container-to-container calls (e.g. the agent fetching an uploaded video) resolve against this, not the host machine's own view of itself. `--external-ip` must be `localhost` — a browser reaching the VM through an SSH tunnel can only resolve `localhost`, not the VM's real IP. Getting `--host-ip` wrong produces "WebSocket is not connected"; using `localhost` where `--external-ip`'s value belongs (or vice versa) produces a connectivity error hitting `localhost:30888` during port generation. Confirmed values for this VM: `--host-ip 10.131.1.5 --external-ip localhost` — see §3 below.
- **Never run `dev-profile.sh down`.** It runs `docker compose down -v` and then deletes the entire data directory, including ~35GB of cached model weights that would otherwise need re-downloading. Use plain `docker compose down` (no `-v`) instead.
- **`dev-profile.sh up` writes to a shared CLI `.env` template, not just the per-deploy config** — switching between deployment styles repeatedly (e.g. testing local, then trying remote, then back) leaves stale values (routing type, base URLs) behind unless every relevant value is explicitly re-passed each time. Recommendation: maintain a dedicated `generated.env.local` file for this deployment style specifically, always invoked with `--env-file generated.env.local` explicitly, rather than relying on `dev-profile.sh`'s incremental CLI-flag behavior.
- **Cold start takes ~6–7 minutes total.** A 503 during that window is expected, not a bug — check `docker ps -a` before assuming something's broken.

---

## 2. Docker + Local Dev Guide

**Backend on the VM** (standard flow from the `vss-deploy-profile` skill, targeting the new `dev-profile-incident`, local LLM/VLM):
```bash
cp deploy/docker/developer-profiles/dev-profile-incident/.env deploy/docker/developer-profiles/dev-profile-incident/generated.env.local
docker compose --env-file generated.env.local config > resolved.yml
# MVP1: bring up only the base-equivalent containers by name (vss-agent-ui excluded — Streamlit is the default UI, see the Overview doc's Context)
docker compose --env-file generated.env.local -f resolved.yml up -d vss-agent incident-console <vios-containers> <nemotron-3-nano container> <vlm container> redis phoenix
# MVP2: bring up everything else already tagged bp_developer_search_2d — RT-CV (vss-rtvi-cv), the search embedding/indexing
# pipeline (vss-behavior-analytics, vss-video-analytics-api — NOT generic analytics, this IS the search pipeline in this
# profile, see the Overview doc §2 MVP1/MVP2 Summary), Elasticsearch/Logstash/Kibana, Kafka, SDRC (routing controller)
docker compose --env-file generated.env.local -f resolved.yml up -d
```
**Never `dev-profile.sh down`** — see §1's operational gotchas. Bringing the stack back up after a clean `docker compose down` should skip the NIM download/build step and only re-hit the cold-start window (§1).

**New incident-console app locally — no Docker, no GPU.** `incident-console/` is its own `uv`-managed Python package (`pyproject.toml` + `uv.lock`, same convention as `services/agent`), not a container, for local dev — Docker bind-mount hot reload has more overhead than just running the process natively:
```bash
cd dev-profile-incident/incident-console
uv sync
uv run streamlit run app.py
```
This gets native hot reload (Streamlit's own `runOnSave`, no container involved) and needs nothing GPU-backed to run most of the app:
- **Postgres:** point `INCIDENT_DB_DSN` at the real Hyperdrive-backed instance directly — no local Postgres, no fixture-seeding to maintain. Catalog, metadata edits, report edit/verify, notifications, dashboard, and eval-log all go straight to it and have zero GPU dependency by design (the shared doc's §3, "direct Postgres, not REST" decision). The only care needed: this is shared state across the team, so use an obvious convention for anything you insert yourself (e.g. a `test-` prefix) rather than editing real rows.
- **The two AI-trigger endpoints (shared doc §4)**, the only GPU-touching part of the app: don't require a real NIM or Elasticsearch to exercise, even in a local-deployment plan. Both `report_agent` and `search_agent` talk to their LLM/VLM over a plain OpenAI-compatible `/v1/chat/completions` `base_url` (confirmed — every `llms:` entry in `dev-profile-base/vss-agent/configs/config.yml` is `_type: nim` or `_type: openai` hitting a `base_url` this way). So for local frontend/API iteration specifically: run the *real* `vss-agent` locally too (per "Agent code locally" below), but point its `LLM_BASE_URL`/`VLM_BASE_URL` at a small local mock server instead of a real NIM — a tiny FastAPI/Uvicorn app implementing `POST /v1/chat/completions` and returning a canned completion shaped like `IncidentReport`, its own small `uv`-managed package (or folded into `incident-console`'s), run the same way: `uv run uvicorn mock_llm_server:app --port <LLM_PORT>`. This exercises the *real* route → tool-calling → schema-extraction → Postgres-write path with zero GPU, zero NIM container, zero Elasticsearch — a deliberate escape hatch from the local-NIM path for the sake of fast local iteration, not a statement that the deployed stack itself runs remotely. (A simpler fallback — mocking the two endpoints directly instead of the LLM — is less code but only useful for pure frontend-shape iteration once the response contracts are stable, since it bypasses `vss-agent`'s own logic entirely.)
- **Video playback:** `st.video(url)` points straight at an R2 URL once a video exists there — no VIOS/NvStreamer/agent involvement for playback (only upload goes through the agent's contract). Point at real test-fixture R2 videos; no backend needs to be running for this at all.

Reachable over the Tailscale hostname when pointing at the real VM-hosted `vss-agent` instead of a local one.

**Existing UI locally (optional, if still wanted for chat/search demos):**
1. `docker compose ... up -d --scale vss-ui=0`
2. `cd services/ui && npm install && npx turbo dev --filter=./apps/nv-metropolis-bp-vss-ui`
3. Point `NEXT_PUBLIC_*` vars at `http://<tailscale-host>:<HAPROXY_PORT>/...`

**Agent code locally:** `services/agent` is a normal uv-managed Python package — run locally against the VM's exposed NIM/VIOS/Postgres, or `docker compose up -d --build vss-agent` on the VM for a fast single-container rebuild.

**VIOS:** no dev-server mode — rebuild image + `docker compose up -d --force-recreate <vios-service>` on the VM.

---

## 3. Reference: NVIDIA Stock Profile Configs (base/search — not `dev-profile-incident`)

Verified/derived configs for running NVIDIA's own `base`/`search` profiles directly under local LLM/VLM mode. Copy-paste commands live in the Overview doc, §1.3. **This is reference material only — not part of the `dev-profile-incident` build**, kept here because it's directly relevant prior art for §1's open topology question.

### Base — local (verified working)

One model per GPU (`--llm-device-id 0`, `--vlm-device-id 1`) — confirmed this is what fixed a crash loop. This validates §1's flag: sharing one GPU between LLM+VLM (as this plan's `local_shared` topology originally assumed) is the untested/risky configuration, not the safe default.

`--hardware-profile OTHER` is required since the A6000 isn't one of NVIDIA's tuned classes. Override file contents (resolves §1's two previously-incomplete sizing gaps):

`vss-llm-override.env`:
```
NIM_KVCACHE_PERCENT=0.8
NIM_GPU_MEM_FRACTION=0.8
NIM_MAX_NUM_SEQS=4
NIM_MAX_MODEL_LEN=128000
NIM_LOW_MEMORY_MODE=1
```

`vss-vlm-override.env`:
```
NIM_KVCACHE_PERCENT=0.8
NIM_GPU_MEMORY_UTILIZATION=0.8
NIM_PASSTHROUGH_ARGS="--gpu-memory-utilization 0.8"
NIM_MAX_MODEL_LEN=32768
NIM_MAX_NUM_SEQS=4
MAX_JOBS=4
NIM_DISABLE_MM_PREPROCESSOR_CACHE=1
NIM_DELETE_LAST_FRAMES=1
```

`--host-ip 10.131.1.5` (real VM IP, for container-to-container calls) / `--external-ip localhost` (for the browser via SSH tunnel) — resolves §1's flagged `--host-ip`/`--external-ip` gap with this VM's actual confirmed values.

### Search — local (derived from VSS docs, not yet run live — verify with `docker logs vss-rtvi-cv` before trusting for a demo)

`dev-profile-search/generated.env` (search-only settings — `RT_CV_DEVICE_ID`/`RT_EMBED_DEVICE_ID`/`NUM_STREAMS` have no CLI flag, so they're set here):
```
RT_CV_DEVICE_ID=0
RT_EMBED_DEVICE_ID=1
NUM_STREAMS=8            # 48GB-class card — not H100's default of 16
```
```bash
./deploy/docker/scripts/dev-profile.sh up --profile search --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 --llm-device-id 1 \
  --llm-env-file /srv/rise-up/vss-llm-override.env \
  --vlm nvidia/cosmos3-reasoner --vlm-device-id 0 \
  --vlm-env-file /srv/rise-up/vss-vlm-override.env
```
Same shape as Base — local above, and the same `--llm`/`--vlm`/`--llm-device-id`/`--vlm-device-id`/`--llm-env-file`/`--vlm-env-file` flags — these apply to any profile, not just base. Device IDs are flipped (LLM→1, VLM→0) to match search's documented layout. Search has up to 4 GPU consumers (RT-CV, RT-Embed, LLM, VLM) on only 2 GPUs, so co-location is required — this is VSS's own documented default split, not one invented for this plan.

**The override files need re-tuning for search** — base's dedicated values (`NIM_KVCACHE_PERCENT=0.8` for both) assume a GPU with nothing else on it; search shares each GPU with RT-Embed/RT-CV, so the budget shrinks:
- GPU 0 VLM sizing: `NIM_KVCACHE_PERCENT ≈ 0.45` (for an 18–21GB-class VLM)
- GPU 1 LLM sizing: `NIM_KVCACHE_PERCENT=0.65` (RT-Embed gets a flat ~10GB budget, LLM gets the rest)

**These two values are derived, not verified** — unlike Base's dedicated `0.8` values above (confirmed working), these are calculated, not yet run live. Flag clearly if this ever gets written up formally.

Directly informs, but doesn't resolve, §1's open question of whether `dev-profile-incident`'s own local topology should reuse this exact split.
