# VSS Customization Plan — Incident Search & Reporting Capstone (Overview)

*This is the human-facing half of the plan — decisions, rationale, and what ships when, written for reviewing/deciding rather than implementing. Exact file paths, config keys, and technical detail live in three companion documents: `incident-plan-implementation-local.md` and `incident-plan-implementation-remote.md` ("the Implementation docs") cover the deployment-mode-specific fork — profile/LLM/VLM setup and GPU topology (§1), the dev/deploy guide (§2), and the stock-profile reference (§3) — while `incident-plan-implementation-shared.md` ("the shared doc") covers everything mode-independent (Postgres, R2, frontend, API, Feature Implementation, Engineering Evaluation, directory tree). Below, "the Implementation doc" as generic shorthand means whichever mode doc applies; where a reference is specifically about LLM/VLM setup, both filenames are named explicitly.*

## Context

Daniel's team is building a video-driven incident search and reporting system on this VSS blueprint fork, sponsored by NVIDIA NVAITC (NVIDIA AI Technology Center) — `origin` is the team's fork (`Danwidj/video-search-and-summarization`), `upstream` is NVIDIA's repo. Sequencing is by dependency, not calendar. Capabilities are described by what they do, not by epic/story number (that doc is still being refined).

**Environment:** `kwanz-ws` — 2× RTX A6000 (48 GB VRAM each, Ampere, same sizing tier as L40S/A40, not H100-tier), Threadripper PRO 5975WX, 251 GiB RAM, 1.8 TB NVMe. Reachable over Tailscale (`kwanz-ws.tailf3aa43.ts.net`) — HAProxy's ACLs already allow that hostname, so teammates on the tailnet hit the deployed stack directly.

---

## 1. Development Guide

### 1.1 Collaboration model

- This VM is the shared dev/deploy target. Teammates on Tailscale hit the deployed stack directly.
- For active UI/agent-code iteration without contending over the one VM, see the Implementation doc, §2 Docker + Local Dev Guide.
- Push WIP branches early so teammates can review without SSH access to this VM.
- Persistent memory file `project_incident_search_capstone.md` is the source of truth for scope/roles across sessions — update it once the current epics are approved, since it currently reflects the original problem statement, not this level of detail.

### 1.2 Operational hazards (read before your first deploy, either mode)

- **Never run `dev-profile.sh down`.** It runs `docker compose down -v` and then deletes the entire data directory — under local LLM/VLM hosting that includes ~35 GB of cached model weights, forcing a full re-download. Use plain `docker compose down` (no `-v`) instead, regardless of which LLM/VLM mode is active.
- **Cold start takes real time** — several minutes, longer under local hosting (NIM containers building/downloading on first run) than remote. A `503` early in that window is expected, not a broken deploy — check `docker ps -a` before assuming something's wrong.
- **Switching between local and remote repeatedly is not free.** `dev-profile.sh up` writes to a shared CLI `.env` template rather than a clean per-deploy file, so values can go stale between switches unless everything relevant is explicitly re-passed each time — see either Implementation doc's §1/§2 for the recommended fix (a dedicated `generated.env.local`/`generated.env.remote` file per mode).

### 1.3 Running NVIDIA's stock profiles (reference only)

**These run NVIDIA's own `base`/`search` profiles directly — not `dev-profile-incident` or anything under development. Reference/comparison only.** Full config and rationale for each: Implementation doc (local/remote as applicable), §3.

**Base — local LLM/VLM (verified working):**
```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a

./deploy/docker/scripts/dev-profile.sh up --profile base --hardware-profile OTHER \
  --host-ip 10.131.1.5 \
  --external-ip localhost \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 --llm-device-id 0 \
  --vlm nvidia/cosmos3-reasoner --vlm-device-id 1
```
GPU tuning values now live in `deploy/docker/services/nim/nvidia-nemotron-nano-9b-v2/hw-OTHER.env` and `deploy/docker/services/nim/cosmos3-reasoner/hw-OTHER.env` directly — `--llm-env-file`/`--vlm-env-file` are no longer needed (verified: dedicated-split local deploy confirmed working from `hw-OTHER.env` alone, no override flags).

**Base — remote LLM/VLM (`openai`-type; verified working end-to-end: real chat completion + real video-understanding call against actual footage):**
```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a
export LLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export VLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export OPENAI_API_KEY="$NVIDIA_API_KEY"

./deploy/docker/scripts/dev-profile.sh up --profile base --hardware-profile OTHER \
  --host-ip 10.131.1.5 \
  --external-ip localhost \
  --use-remote-llm --llm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning --llm-model-type openai \
  --use-remote-vlm --vlm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning --vlm-model-type openai
```
Corrected from an earlier version that used `--host-ip localhost` — see Implementation doc (remote), §3 for why that was wrong and what's actually been verified. **`openai`-type, not `nim`-type**: a prior fix attempt switched this block to `--llm-model-type nim --vlm-model-type nim` (reasoning: authenticate directly via `NVIDIA_API_KEY`, sidestep the `openai_vlm` missing-`base_url` bug) — live verification found `nim`-type currently non-functional, 100% call failure, due to an upstream `nvidia-nat` bug (`nim_langchain`'s builder leaks `verify_ssl` into the request body; tracked upstream as issue #1894/PR #1862, unmerged, no fixed release exists as of 2026-09-06). `openai`-type does not hit that bug and is the confirmed-working path. This does require patching the `openai_vlm` missing-`base_url` bug (see below) — that fix is real and still needed, just applied here instead of sidestepped.

Required config fix for this path: `deploy/docker/developer-profiles/dev-profile-base/vss-agent/configs/config.yml` and `config_rag.yml`'s `openai_vlm` client block is missing `base_url` (present on every sibling block — `nim_llm`, `openai_llm`, `nim_vlm`); without it, remote VLM calls default to the real `https://api.openai.com` instead of NVIDIA's endpoint. Add `base_url: ${VLM_BASE_URL}/v1` to that block, mirroring the sibling blocks exactly.

Known separate, non-blocking issue if reused for longer clips: `config.yml`'s shared `max_frames: 30` (sampled at `max_fps=2`) exceeds this hosted model's 12-image-per-prompt cap for clips longer than ~12 seconds — produces a `500: At most 12 image(s) may be provided in one prompt` error. Not specific to `openai`-type (would affect `nim`-type equally once its bug is fixed). No fix applied yet — options are lowering `max_frames`/`max_fps` for remote use, or chunking longer clips into sub-12-image windows (as done to verify this path) rather than sending a whole long clip in one call.

Known non-blocking condition either way: NVIDIA's free hosted tier has a shared, global 16-concurrent-request ceiling (`503 ResourceExhausted`) — `nvidia-nat`'s own automatic retry-with-backoff handles it transparently in practice.

**Search — local LLM/VLM (derived from VSS docs, not yet run live).** **TODO: search profile deployment (local and remote) is deferred — device layout below is known-broken for this 2-GPU host and needs redesign before use. Do not rely on this block yet.**
```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a

./deploy/docker/scripts/dev-profile.sh up --profile search --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --llm nvidia/nvidia-nemotron-nano-9b-v2 --llm-device-id 1 \
  --llm-env-file /srv/rise-up/vss-llm-override.env \
  --vlm nvidia/cosmos3-reasoner --vlm-device-id 0 \
  --vlm-env-file /srv/rise-up/vss-vlm-override.env
```
Same `--llm`/`--vlm` flags as Base above (they apply to any profile), device IDs flipped to match search's layout. `RT_CV_DEVICE_ID`/`RT_EMBED_DEVICE_ID`/`NUM_STREAMS` have no CLI flag — set via `dev-profile-search/generated.env` — see Implementation doc (local), §3.

**Search — remote LLM/VLM (derived from VSS docs, not yet tested).** **TODO: same deferral as Search — local above; also missing `--llm-model-type`/`--vlm-model-type` — use `openai` per the now-verified Base — remote block above, not `nim` (see that block's note for why).**
```bash
cd /srv/rise-up/vss
set -a; source /srv/rise-up/.ngc_env; set +a
export LLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export VLM_ENDPOINT_URL='https://integrate.api.nvidia.com'
export OPENAI_API_KEY="$NVIDIA_API_KEY"

./deploy/docker/scripts/dev-profile.sh up --profile search --hardware-profile OTHER \
  --host-ip 10.131.1.5 --external-ip localhost \
  --use-remote-llm --llm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning --llm-model-type openai \
  --use-remote-vlm --vlm nvidia/nemotron-3-nano-omni-30b-a3b-reasoning --vlm-model-type openai
```
`RT_CV_DEVICE_ID`/`RT_EMBED_DEVICE_ID`/`NUM_STREAMS` still go in `dev-profile-search/generated.env` (perception/embedding stay local even under remote LLM/VLM, and have no CLI flag) — see Implementation doc (remote), §3.

**Reaching the UI (all four configs above):** `ssh -N -L 7777:10.131.1.5:7777 daniel@kwanz-ws`, browse `http://localhost:7777`. This is how you reach the box over SSH tunnel, independent of where the LLM/VLM run.

---

## 2. MVP1 / MVP2 Summary

**Deployment model:** a new profile, `dev-profile-incident/`. It reuses NVIDIA's `bp_developer_search` compose tag — confirmed superset of everything base needs (Implementation docs §1) — with one `config.yml` that grows from MVP1 to MVP2.
- MVP1 = base's report-generation config (`report_agent`/`video_report_gen`) as the starting point. MVP2 *appends* search's functions (`search_agent`/`embed_search`/etc.) — not a strip-down, since search's config has zero report-generation today.
- MVP2 also brings up RT-CV (VSS's real-time computer-vision perception service) and the `behavior-analytics`/`video-analytics-api` pair — this *is* the search pipeline in this profile, not optional analytics (see capability breakdown below).
- Everything we build (Streamlit console, new tools, API routes) stays inside `dev-profile-incident/` or `services/agent`'s own extension points — never in shared `deploy/docker/services/`.
- VIOS (VSS's Video I/O Storage service) runs SDRC-routed from MVP1 on (SDRC = VSS's routing controller for RTSP camera registration), since search needs it anyway — avoids a mid-project routing migration.

Capability breakdown (technical mechanics: Implementation doc §1, §2; shared doc §5):

- **MVP1** — everything except natural-language search: video catalog, upload, metadata editing, retention; report generation and all its fields (event description, key persons, incident classification, start-time detection); one-click pipeline trigger, status transitions, high-severity notifications; all frontend UI except the search box; human-eval flow and engineering report-quality scoring.
- **MVP2** — adds natural-language search. The pipeline's "NIM indexing" leg (a no-op in MVP1) becomes meaningful, and the retrieval precision/recall/F1 notebook becomes exercisable.

---

## 3. Verification

What "done" looks like per capability area — see the Implementation doc for the exact queries/commands behind each check.

- **Data & Dataset:** upload a video, confirm it appears in the catalog with correct status and count; edit metadata, confirm it's reflected in a report generated afterward.
- **AI & Video Intelligence:** generate a report, confirm every structured field populates and degrades gracefully on ambiguous input (empty persons list, unconfirmed start time).
- **Workflow & Automation:** run the full-pipeline trigger end to end, confirm status moves through its full lifecycle (including an induced failure), confirm verifying a report creates a notification per whatever severity cutoff the team confirms (the shared Implementation doc, §5, flags the default used here as unsourced from any spec).
- **Frontend & UX:** confirm search/filter, timestamp-jump, edit/verify, and dashboard charts reflect real data from a handful of test reports; clear filters, confirm the full set returns.
- **Evaluation & Testing:** rate a small sample manually, confirm the agreement-rate calculation matches a hand-computed value.
- **R2/Postgres:** live smoke test — record/upload a clip, confirm it lands in R2 and is retrievable; generate a report, confirm the row lands correctly in Postgres.

---

## 4. Alignment Check — Feature Scope vs. Proposal vs. VSS Capabilities

**Note:** this section originally cited the team's epic/story numbers directly; since that document is still being refined, the comparisons below are described by capability instead, so they stay valid as the numbering changes. Re-check against whatever the current epic/story doc says before treating any of this as settled.

**Vs. the original proposal (`project_incident_search_capstone.md`):** consistent, no contradictions.
- NL search = the proposal's semantic-search objective.
- Structured report generation = the Nemotron-3 structured-report objective.
- Trend/priority dashboard = the triage/prioritization/trend-analysis deliverable.
- Human-eval flow + the shared doc's engineering evaluation harness (§6) = the proposal's precision/recall/F1 + report-quality requirement.
- Both personas map 1:1.
- Video catalog/upload/retention and status-transition/notification aren't named explicitly in the proposal but are natural supporting infrastructure, not scope creep.

**Vs. what VSS actually ships:** uneven, worth knowing which is which —
- **Report generation is mostly a wrapper, not new AI.** `video_report_gen` already does chunked/timestamped summarization and narrative reports; the structured-field work mostly extracts fields from what VSS already produces.
- **The catalog, workflow/notifications, dashboard, and evaluation capabilities are mostly new product engineering.** VSS has no native video catalog, status workflow, notifications, dashboard, or human-eval UI — expected, since VSS is a video-AI backend, not an incident-management product.
- **Natural-language search needs MVP2's search stack** (RT-Embed + Elasticsearch) — not active in MVP1. Matches the proposal's own framing of NL search as due by final, not midterm, so MVP1-first sequencing doesn't conflict — but the project's headline capability isn't demoable until MVP2.

---

## 5. Judgment Calls

Not derivable from the code — decisions made this round:
- **Frontend:** a new dedicated app in Python + Streamlit, kept independent of `services/ui` (see Implementation doc §2, "Existing UI locally") — matches the capability needs (shared doc §3) and the original proposal's own stated stack.
- **Pipeline orchestration:** extend vss-agent's own tool-calling, not a separate orchestrator service.
- **LLM/VLM hosting:** two supported configs, picked per situation, not a single fixed choice.
  - **Local** (2 GPUs) — no rate limits, but VRAM-constrained model choice and an untested GPU-sharing risk (NVIDIA's own guidance is one model per GPU on 2-GPU hosts; a real crash precedent exists for sharing).
  - **Remote** (1 GPU) — unconstrained model choice, but a confirmed 16-concurrent-request ceiling that report generation can saturate, with no self-service fix (a better remote option is being scouted, status pending). Full detail: `incident-plan-implementation-local.md` / `-remote.md`, §1.
- **Retention & auth:** R2 = canonical video store, Postgres = canonical report store; local VIOS disk is a working cache, not the source of truth. No real accounts — attribution fields (`edited_by`, `verified_by`) are freeform text.
