# Incident Search & Reporting Capstone — Overview

## 1. What this is

Video-driven incident search and reporting built on this VSS blueprint fork. A Streamlit console (`incident-console`) sits on Postgres (reports) + R2 (video), triggers report generation and search through `vss-agent`, and runs inside a new `dev-profile-incident` deployment profile.

## 2. Where things live

- Plan docs: `docs/incident-plan/` (this file; `incident-plan-implementation-local.md` / `-remote.md` for mode-specific setup; `incident-plan-implementation-shared.md` for mode-independent build).
- Profile: `deploy/docker/developer-profiles/dev-profile-incident/` (`compose.yml`, `incident-console/`, `mock-backend/`, `LOCAL_MOCK_LOOP.md`).
- Console schema, authoritative: `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py` (module docstring + `incident-console/README.md`).
- GPU-less UI loop: `mock-backend/base_profile_mock/README.md` and `LOCAL_MOCK_LOOP.md`.
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
- Local UI iteration needs no GPU/VM: `cd deploy/docker/developer-profiles/dev-profile-incident/incident-console && uv sync && uv run streamlit run app.py` (see `LOCAL_MOCK_LOOP.md`).

## 5. Current status (as of 2026-09-13)

| Item | State |
|---|---|
| `incident-console` app (catalog, report review, dashboard, human-eval; Postgres-backed, no offline mode) | Present; seed via `incident-console/scripts/seed_supabase.py` over `fixtures/data/*.csv` |
| Console schema (`db.py`: videos/queries/model_runs/incidents + evidence, ground-truth, match, review tables) | Present; authoritative for schema questions |
| Mock backend + local loop (`mock-backend/base_profile_mock`, `LOCAL_MOCK_LOOP.md`) | Present; verified loop documented |
| Stock base-local deploy (one model per GPU, `hw-OTHER.env` sizing) | Verified working |
| Stock base-remote chat + VLM describe (`openai`-type, model above) | Verified working 2026-09-13 on corrected `--host-ip`: video upload to VST plus `video_understanding` through the remote VLM returned a correct description. Full `report_agent` path still needs a UI websocket (HITL), so it remains unverified headless. |
| Stock `search` profile (local and remote) | Not run live; device layout deferred, do not rely on it |
| `dev-profile-incident` `config.yml`, `incident_report_gen` tool, `/analyze` + `/search` API routes | Planned (shared doc §§4-6); not yet built |
| `openai_vlm` missing-`base_url` patch (`base_url: ${VLM_BASE_URL}/v1` in `config.yml` + `config_rag.yml`) | Required; re-apply after any upstream sync |
| Remote free-tier 16-concurrent-request ceiling; hosted-model 12-images-per-prompt cap | Open constraints; remote report path loops/hangs past them |

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
