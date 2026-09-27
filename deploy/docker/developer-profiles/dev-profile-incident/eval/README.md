# P1/RP1 evaluation pipeline

This is a standalone **Python** subproject, living at the `dev-profile-incident` profile root alongside
`incident-console/`, `incident-console-v2/`, and `vlm-gateway/` - not nested inside any of them. It runs as its own
separate Python process with its own virtual environment and shares no code or runtime with any other service in
this profile beyond the copied modules below.

It evaluates structured incident extraction ("P1") across three VLMs on held-out video, and generates ("RP1", never
scored) a human-readable report per prediction. The recorded benchmark in
[`docs/vlm_benchmark_results.md`](docs/vlm_benchmark_results.md) predates the incident contract (it used P1-v1 with
few-shot and base64 video), so it is superseded until the contract run is recorded.

## Why it needs incident-console's modules

The scoring/matching/DB-access code this pipeline depends on (`matching.py`, `eval_gt.py`, `config.py`, `db.py`,
`db_connection.py`, `embed_client.py`, `incident_report.py`, `r2_videos.py`) is copied verbatim from
`incident-console` - it is the same scoring and data-access code, not a reimplementation, and not wired back to the
original (no shared imports, no shared `sys.path` entry). The original `incident-console` copy is unaffected by
this and continues to work independently. Two files carry a small, deliberate path-resolution note for their
directory depth (one level under `dev-profile-incident/`, the same depth as `incident-console/`) - see the comments
in `config.py` (`.env` loading) and `scripts/eval_vlm_client.py` (`ENV_LOCAL`).

The Streamlit UI itself (`app.py`, `report_detail.py`, and the other page modules) was **not** copied - this
project only runs the batch evaluation, never a UI.

## Setup

```bash
cd deploy/docker/developer-profiles/dev-profile-incident/eval
uv sync
```

Required environment variables (read from `.env.local`, a symlink to `../.env.local`, i.e. the same
`dev-profile-incident/.env.local` every other service in this profile shares):

| Variable | Purpose |
|---|---|
| `INCIDENT_SUPABASE_URL`, `INCIDENT_SUPABASE_SERVICE_ROLE_KEY` | PostgREST access to the ground-truth/incidents tables (used when direct Postgres, `INCIDENT_DB_DSN`, is unreachable) |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET` | Video resolution and signed URLs from Cloudflare R2 |
| `VLM_GATEWAY_API_KEY` (or `INCIDENT_LLM_API_KEY`, same value) | P1/RP1 inference calls through `vlm-gateway` |
| `INCIDENT_LLM_BASE_URL` | Chat-completions endpoint (the switchyard gateway URL, not the mock) |
| `INCIDENT_JUDGE_MODEL` | LLM-judge model for the `description` field's semantic score |
| `INCIDENT_EMBEDDING_BASE_URL` | Points at a locally-run `scripts/eval_embedding_server.py` instance (`sentence-transformers/all-MiniLM-L6-v2`; no remote embeddings endpoint exists for this deployment) |

None of `INCIDENT_LLM_API_KEY`, `INCIDENT_JUDGE_MODEL`, or a real `INCIDENT_EMBEDDING_BASE_URL` value ship in the
committed `.env` placeholder - if they're missing from `.env.local`, add them before running anything live.

## What P1 sends (incident contract)

P1 follows the shared [incident contract](../contracts/README.md) (`incident-contract-v2`), which is the same prompt, schema and request shape the console and agent move to in phases 2 and 3 of [`../.docs/prompt-contract-plan.md`](../.docs/prompt-contract-plan.md):

- one video as a **signed R2 URL** (never downloaded or base64-inlined), placed before the contract's extraction prompt;
- the schema enforced with `response_format: json_schema` (strict);
- the fixed configuration `temperature 0`, `max_tokens 16384` and `media_io_kwargs {"video": {"num_frames": 64}}`, identical for every model (`eval_vlm_client.P1_INFERENCE_CONFIG`);
- **no few-shot examples.** The earlier category-specific block leaked the label.

The response is judged by [`contract.py`](contract.py) `evaluate_policy` under validation policy **`core-scored-v1`** ([`../contracts/README.md`](../contracts/README.md)). The raw content must be one JSON document and pass the schema; nothing is repaired or extracted from surrounding text. `incident.duration` is derived as `end - start`.

- **Scored fields:** only the database-backed fields (incident type, window, description, severity; entities, instruments, assets). Title, severity rationale, location, timeline and uncertainties are never scored.
- **`p1_raw.contract_ok` / `contract_error`:** full incident-contract validity, meaning unchanged: schema plus every cross-field rule.
- **`p1_raw.core_ok`:** decides scoring. The prediction is scored when its database-backed fields are valid; otherwise it is an empty prediction (a miss). A failure confined to the unscored fields, e.g. a timeline outside the incident window, never empties it.
- **Video length:** read from each clip's MP4 header ([`video_duration.py`](video_duration.py), ranged R2 reads). An incident window outside the video is a core failure. An unreadable length means the rule is not applied (`video_bounds_checked: false`).
- **`validation` block, per video:** contract version, policy, both validities, core and enrichment violations (with codes), video length.
- **Aggregate:** `p1_failures` are the misses. `contract_failures`, `core_failures` and `enrichment_violation_videos` are diagnostics, outside every quality score.
- **RP1:** still runs only on fully contract-valid responses.
- **Files:** each run also writes a never-overwritten copy of every results file under `eval_data/results/runs/<run start>/`, so the raw responses, versions, diagnostics and inference settings of past runs stay available for re-scoring without another VLM call. Results written before `core-scored-v1` were scored by full contract validity; the summary lists each model's `validation_policies`.

The split manifests are unchanged, so results stay comparable video-for-video with the earlier run. The 5 former few-shot demonstration videos per category are still excluded from evaluation.

## Running

```bash
# 1. Start the local embedding server (separate terminal, stays running)
uv run python scripts/eval_embedding_server.py   # prints the INCIDENT_EMBEDDING_BASE_URL to set

# 2. Ground truth: ingest the real (not demo) workbook once
uv run python scripts/eval_ingest_gt.py

# 3. Generate the per-category demonstration/evaluation split once (seeded, persisted)
uv run python scripts/eval_generate_split.py

# 4. Run the batch evaluation
uv run python scripts/eval_run.py                 # full run: all 3 models, all 5 categories
uv run python scripts/eval_run.py --models nvidia/cosmos-3-nano-reasoner --categories Assault --limit 1  # smoke test

# 5. Cross-category/cross-model aggregation
uv run python scripts/eval_aggregate.py
```

Tests: `uv run pytest tests/` - hermetic, no live Postgres/agent/GPU required (see `tests/conftest.py`).
