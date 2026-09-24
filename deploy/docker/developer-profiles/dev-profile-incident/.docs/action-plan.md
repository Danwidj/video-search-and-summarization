# Incident Search & Reporting Capstone — Action Plan

This document outlines the goals, scope, and implementation plan for the Incident Search and
Reporting profile (`dev-profile-incident`), built as a capstone project on NVIDIA's Video Search and
Summarization (VSS) Blueprint and sponsored by NVIDIA NVAITC.

---

## 1. Goals and Intended Outcomes

The objective is to build an intelligent, video-driven incident search and reporting system for
physical security, warehouse operations, and anomaly monitoring footage.

The system replaces manual video inspection with automated Vision-Language Model (VLM) analysis:
1. **Ingest surveillance and anomaly video clips** via high-throughput video streaming infrastructure.
2. **Extract structured, timestamped incident intelligence** (incident classification, severity,
   confidence, summary, observed entities, weapons/instruments, affected assets, and event timeline).
3. **Facilitate human review, editing, and verification** of AI findings through an interactive web
   console with high-severity alert notifications.
4. **Benchmark AI output quality** against human ground truth through automated evaluation.
5. **Enable natural language video retrieval** (MVP2) across video archives using multi-modal embeddings
   and vector search.

---

## 2. Scope Breakdown: MVP1 vs. MVP2

Development is partitioned into two major milestones. MVP1 delivers the end-to-end incident analysis
and reporting loop; MVP2 adds natural-language semantic video search.

```
+-----------------------------------------------------------------------------+
|                                    MVP1                                     |
|                      (Incident Report Generation)                           |
|                                                                             |
|  +------------------+    +--------------------+    +---------------------+  |
|  | Video Ingestion  | -> |   VLM / Agent AI   | -> | Interactive Review  |  |
|  | (NvStreamer/R2)  |    | Report Generation  |    | & Verification (UI) |  |
|  +------------------+    +--------------------+    +---------------------+  |
|                                      |                                      |
|                                      v                                      |
|                          +-----------------------+                          |
|                          | Ground-Truth Eval (T1)|                          |
|                          +-----------------------+                          |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                                    MVP2                                     |
|                       (Natural-Language Search)                             |
|                                                                             |
|  +------------------+    +--------------------+    +---------------------+  |
|  | Perception/Embed | -> |   Elasticsearch    | -> | Multi-Subagent      |  |
|  | (RT-CV, RT-Embed)|    | Vector & Metadata  |    | Search (/search)    |  |
|  +------------------+    +--------------------+    +---------------------+  |
|                                      |                                      |
|                                      v                                      |
|                          +-----------------------+                          |
|                          | Retrieval Eval (P/R/F)|                          |
|                          +-----------------------+                          |
+-----------------------------------------------------------------------------+
```

### MVP1: Incident Report Generation

*Focus: Ingestion, automated analysis, structured metadata extraction, human verification, and ground-truth evaluation.*

- **Scope:**
  - **Video Ingestion & Storage:** Upload video clips through VST/NvStreamer chunked upload and persist
    canonical copies in Cloudflare R2 object storage.
  - **Automated Analysis Pipeline:** Trigger VLM inference over uploaded footage (via either the local
    credential-holding `vlm-gateway` or the native `vss-agent`'s `POST /api/v1/incidents/{incident_id}/analyze`
    endpoint).
  - **Structured Incident Extraction:** Populate normalized incident reports with:
    - Incident classification / taxonomy type (`road accident`, `burglary`, `explosion`, `fighting`, `animal`).
    - Severity rating (integer 1–5) and explicit reasoning.
    - Confidence score (float 0.0–1.0).
    - Incident description / summary.
    - Start and end timestamps with duration in seconds.
    - Key entities observed (persons, actors, descriptions, actions).
    - Observed instruments, tools, or weapons with threat levels (1–5).
    - Impacted or observed assets (vehicles, structures, equipment).
    - Chronological event timeline (start/end seconds, event descriptions).
    - Explicit uncertainties and extraction gaps.
  - **Review & Verification UI:** `incident-console-v2` Next.js frontend supporting:
    - Video upload workspace with progress tracking.
    - Incident report view with timestamp seeking, evidence cards, and print styling.
    - Review lifecycle transitions: `unreviewed` -> `under review` -> `verified`.
    - High-severity notifications (severity >= 4).
    - Model run comparison (comparing multiple analyses over the same video).
  - **Ground-Truth Evaluation (Tier 1):**
    - Parallel ground-truth schema (`gt_*` tables) populated from human annotations.
    - Exact match scoring for incident type and severity.
    - LLM-judge qualitative scoring for incident description.
    - Temporal tolerance comparison for start/end timestamps and duration.
    - Entity, instrument, and asset precision, recall, and F1 via embedding similarity and Hungarian matching.

- **MVP1 Success Criteria:**
  - Zero-data-loss video ingestion with durable playback links generated on demand.
  - End-to-end report generation completes reliably without rate-limit deadlocks.
  - AI extraction outputs valid JSON adhering to schema constraints and graceful fallbacks for ambiguous inputs.
  - Review status changes and human verification actions persist atomically to Postgres.
  - Tier 1 evaluation pipeline successfully computes comparative metric scores against ground truth.

---

### MVP2: Natural Language Incident Search

*Focus: Multi-modal embedding indexing, vector search, multi-subagent routing, and retrieval evaluation.*

- **Scope:**
  - **Real-Time Perception & Embeddings:**
    - Real-Time Computer Vision (RT-CV / `vss-rtvi-cv` DeepStream container) for object and motion detection.
    - Real-Time Video Embeddings (RT-Embed / `vss-rtvi-embed`) generating vector representations of video segments.
    - Kafka event bus streaming frame detections and embeddings to Elasticsearch.
  - **Elasticsearch Storage:** Ingest and index multi-modal video embeddings and detection metadata.
  - **Multi-Subagent Agent Configuration:**
    - Wire `search_agent`, `embed_search`, and `attribute_search` alongside `report_agent` in `config.yml`.
    - Implement a unified routing prompt allowing `vss-agent` to dispatch natural-language search queries
      or incident report generation based on incoming requests.
  - **Search API & Console Search Interface:**
    - Expose `POST /api/v1/incidents/search` on `vss-agent`.
    - Add natural language search box in `incident-console-v2` with temporal jump-to-clip capabilities.
  - **Retrieval Evaluation:**
    - Benchmark retrieval precision, recall, Mean Reciprocal Rank (MRR), and F1 across a test set of natural
      language queries paired with ground-truth video segments.

- **MVP2 Success Criteria:**
  - Natural language queries return relevant timestamped video segments within target latency.
  - Subagent routing dispatches search queries accurately without degrading report generation workflows.
  - Retrieval benchmark achieves agreed-upon precision and recall targets across standard incident classes.

---

## 3. Standing Architectural Decisions

The following core principles govern all work in `dev-profile-incident`:

1. **Profile Tag:** Reuses NVIDIA's `bp_developer_search` compose tag. The `BP_PROFILE` variable in `.env`
   remains `bp_developer_search` so the stack is a superset of the base and search pipelines.
2. **Dual Analysis Architecture:**
   - **Gateway Mode (`ANALYSIS_MODE=gateway`):** Fast, zero-GPU local development. The Next.js frontend calls
     `vlm-gateway` (port 8600), which holds the upstream inference key and calls the hosted Brev switchyard endpoint.
   - **Agent Mode (`ANALYSIS_MODE=agent`):** Full blueprint integration. The frontend connects over SSH tunnel
     to the native `vss-agent` (port 8000) on `kwanz-ws`, which invokes remote NGC models and persists reports.
3. **Storage Architecture:**
   - **Cloudflare R2:** The canonical, permanent object store for uploaded videos and evidence frames.
   - **Supabase (PostgreSQL):** The canonical database for incident reports, review workflows, ground truth, and
     evaluations.
   - **Local VIOS Disk:** Acts solely as an ephemeral working cache for video ingestion and streaming.
4. **Data Model Identity Rule:** **1 video = 1 incident.** `incidents.incident_id` is identical to `videos.id`.
   There is no separate `video_id` column.
5. **Multi-Model Run Support:** `incidents`, `entities`, `instruments`, and `assets` are keyed by composite
   primary keys including `model_run_id`, allowing multiple model runs or prompts over the same video without
   collision.
6. **Isolated Review State:** The `review_status` table tracks human review (`unreviewed`, `under review`,
   `verified`) keyed by `(incident_id, model_run_id)` so that the core AI-generated `incidents` table remains
   an immutable record of model output.
7. **VM Network Constraints:** The VM host environment (`kwanz-ws`) blocks raw Postgres wire protocol (port 5432)
   via deep packet inspection (DPI). Therefore, all agent-side database persistence uses HTTPS PostgREST
   (`supabase-py`), while local laptop scripts and tools can connect directly via `INCIDENT_DB_DSN`.
8. **Stateless User Model:** `edited_by`, `verified_by`, and `rater` fields store plain text usernames entered by
   team members; no complex authentication or user account table is required.

---

## 4. Current Status: What is Done vs. Outstanding

*Status is strictly verified against the current repository source code.*

| Component / Feature | Current State | Verifiable Source Files |
|---|---|---|
| **incident-console-v2 (Next.js)** | **Done** | `incident-console-v2/` (App Router UI, chunked VST upload, R2 direct fallback, report workspace, review flow, notification banner, eval form) |
| **vlm-gateway Proxy** | **Done** | `vlm-gateway/app.py`, `vlm-gateway/README.md` (FastAPI proxy on port 8600 holding upstream API credentials) |
| **mock-backend (Zero-GPU)** | **Done** | `mock-backend/base_profile_mock/` (port 7777, mock VST upload, mock stream registration, mock incident analysis) |
| **Agent /analyze Route & Tool** | **Done** | `services/agent/src/vss_agents/routers/incidents.py`, `services/agent/src/vss_agents/tools/incident_report_gen.py` |
| **Native VM Services Architecture** | **Done** | `.scripts/native-services.sh`, `.scripts/prune-native-images.sh` (`vss-agent` runs natively on `kwanz-ws` for 2s fast restarts) |
| **PostgREST Agent Persistence** | **Done** | `services/agent/src/vss_agents/utils/incident_db.py`, `supabase/migrations/20260917141225_insert_incident_function.sql` |
| **Cloudflare R2 Integration** | **Done** | `incident-console-v2/lib/r2/config.ts`, `app/api/uploads/r2/route.ts`, `incident-console/r2_videos.py` |
| **Tier 1 Ground-Truth Evaluation** | **Done** | `incident-console/eval_gt.py`, `matching.py`, `incident-console-v2/app/reports/eval/` |
| **Unified Launcher (`start.sh`)** | **Done** | `start.sh`, `.scripts/tunnel.sh`, `.scripts/status.sh` (supports `--mode local` and `--mode vm` with auto self-heal) |
| **Multi-Subagent Search Config** | **Outstanding (MVP2)** | `config.yml` multi-subagent routing (`report_agent` + `search_agent`) planned; not yet wired together |
| **Natural Language Search Route** | **Outstanding (MVP2)** | `POST /api/v1/incidents/search` on `vss-agent` and UI search box not yet implemented |
| **Full RT-CV + RT-Embed Indexing** | **Outstanding (MVP2)** | DeepStream perception and vector embedding pipeline integration with Elasticsearch under live incident load |
| **Retrieval Benchmark Framework** | **Outstanding (MVP2)** | Precision/Recall/F1 benchmark suite for search queries |
