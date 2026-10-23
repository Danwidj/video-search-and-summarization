# Incident Search & Reporting Capstone - Action Plan

Goals, scope and standing decisions for the Incident Search and Reporting profile (`dev-profile-incident`), a capstone on NVIDIA's Video Search and Summarization (VSS) Blueprint sponsored by NVIDIA NVAITC. Live status: [`status.md`](status.md).

---

## 1. Goals

An intelligent, video-driven incident search and reporting system for physical security, warehouse operations and anomaly footage. It replaces manual video inspection with VLM analysis:

1. **Ingest** surveillance and anomaly clips and keep canonical copies in Cloudflare R2.
2. **Extract** structured, timestamped incident reports: type, severity, confidence, summary, entities, instruments, assets, timeline and uncertainties.
3. **Review** AI findings in a web console (edit, verify, choose an official report per video).
4. **Benchmark** extraction quality against human ground truth.
5. **Search** the archive in natural language over evidence crops and embeddings (MVP2).

## 2. Scope

### Incident reporting (delivered)

- **Ingestion:** VST/NvStreamer chunked upload with a direct-to-R2 fallback; durable playback links generated on demand.
- **Analysis:** either the credential-holding `vlm-gateway` or the native `vss-agent` (`POST /api/v1/incidents/{incident_id}/analyze`), on `incident-contract-v4`, with any of three allowlisted VLMs, strict validation and ID-only recovery. Every attempt is recorded; failures stay in a per-video history.
- **Review UI (`incident-console-v2`):** upload workspace, report view with timestamp seeking and evidence cards, review lifecycle `unreviewed` / `under review` / `verified`, structured reviewer editing that leaves model output immutable, run history and re-analysis, explicit official report per video, and a dashboard that counts official incidents only.
- **Tier 1 ground-truth evaluation (removed):** Formerly `gt_*` tables from human annotations; exact match for type and severity, LLM-judge scoring for the description, temporal tolerance for start/end/duration, and precision / recall / F1 for entities, instruments and assets via embedding similarity and Hungarian matching. The ground-truth evaluation screen and tables have been removed.

### MVP2: natural-language incident search

Specification and architecture: [`mvp2/README.md`](mvp2/README.md). A hybrid pipeline, because VLM bounding boxes scored 0% well-framed while timestamps were over 95% accurate:

- **VLM extraction:** reports with item timestamps (`incident-contract-v4`).
- **Crop pipeline:** keyframes at item timestamps, a detector port for boxes (today the remote VLM; local open-vocabulary detectors are evaluated offline in [`mvp2/eval.md`](mvp2/eval.md)), crops uploaded to R2.
- **Search layer:** metadata and 1024-d text embeddings in `evidence_crops` (HNSW index), queried through the `search_evidence_items` RPC (`service_role` only).
- **Always-on VLM critic:** checks each candidate hit against the query and records verdicts in `query_results`.
- **Frontend:** search route in `incident-console-v2` with filter chips, hit cards with crops and critic rationales, jump-to-clip, and conversational Q&A.
- **Contracts:** `search-contract-v1` and `chat-contract-v1`, with routes in `vss-agent` and the mock backends (ports 7777 / 7778).

## 3. Standing architectural decisions

1. **Profile tag:** reuses NVIDIA's `bp_developer_search` compose tag (`BP_PROFILE` stays `bp_developer_search`), so the stack is a superset of the base and search pipelines.
2. **Dual analysis modes:** `ANALYSIS_MODE=gateway` (Next.js to `vlm-gateway` :8600 to the hosted Brev endpoint; zero GPU) and `ANALYSIS_MODE=agent` (Next.js over an SSH tunnel to the native `vss-agent` :8000 on `kwanz-ws`).
3. **Storage:** R2 is the permanent store for videos and evidence images; Supabase Postgres holds reports, review and evaluations; the VIOS disk is only a working cache.
4. **1 video = 1 incident:** `incidents.incident_id` equals `videos.id`; there is no `video_id` column.
5. **Multi-run support:** `incidents`, `entities`, `instruments` and `assets` are keyed by `model_run_id` as well, so several runs over one video do not collide.
6. **Isolated review state:** `review_status` is keyed by `(incident_id, model_run_id)`, leaving `incidents` an immutable record of model output.
7. **VM network constraint:** `kwanz-ws` blocks port 5432, so agent-side persistence uses HTTPS PostgREST (`supabase-py`); laptop tools may use `INCIDENT_DB_DSN`.
8. **Stateless users:** `edited_by`, `verified_by` and `rater` are plain-text names; there is no account table.
