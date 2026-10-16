# MVP2 Eval Workstream Tasks (Retrieval Benchmark & Detector Test)

## 1. Goal

Evaluate natural-language evidence search quality and visual crop grounding accuracy for MVP2:
1. **Retrieval Benchmark Suite:** Implement an automated benchmark evaluating the `POST /api/v1/incidents/search` endpoint against an independent, curated query-to-ground-truth dataset, measuring quantitative retrieval effectiveness (Precision@K, Recall@K, MRR, F1).
2. **Open-Vocabulary Detector Test:** Conduct an empirical comparative test of candidate open-vocabulary 2D detectors (e.g. Grounding DINO, OWLv2, Florence-2) to identify which detector best frames tight object crops from video keyframes anchored by VLM-predicted timestamps and labels.

---

## 2. Workstream Tasks Checklist

Assignee builds on this branch (`fm/vss-mvp2-eval-handoff`) by completing the following checklist:

- [ ] **Propose Benchmark Query Sourcing Strategy:** Deliver a concrete proposal resolving how the independent evaluation query dataset is assembled (human-curated queries vs LLM-generated variants with human review), ensuring queries avoid circularity with `gt_incidents` descriptions.
- [ ] **Assemble Independent Retrieval Benchmark Dataset:** Curate the benchmark query dataset across diverse query categories (broad surveillance intent, specific entities, instruments/weapons, assets/vehicles) with target incident/item mappings and negative/adversarial distractors.
- [ ] **Implement Retrieval Benchmark Harness (`eval/scripts/eval_retrieval.py`):** Build a standalone evaluation script querying `POST /api/v1/incidents/search` (supporting local mock port 7778 / live `vss-agent` port 8000).
- [ ] **Compute Quantitative Retrieval Metrics:** Calculate Precision@K, Recall@K, Mean Reciprocal Rank (MRR), and F1 score across varying top-K values ($K \in \{1, 3, 5, 10\}$), comparing raw vector retrieval vs Critic-verified ranking.
- [ ] **Design and Execute Open-Vocabulary Detector Test:** Set up an empirical test comparing candidate open-vocabulary 2D detectors (such as Grounding DINO, OWLv2, Florence-2) on the pilot surveillance video clips.
- [ ] **Evaluate Crop Framing Accuracy:** Measure the percentage of well-framed, partly-framed, and missed object crops given VLM-predicted keyframe timestamps (`timestamp_seconds`) and item labels/descriptions, reusing the box pilot contact sheet methodology.
- [ ] **Deliver Detector Recommendation Report:** Document quantitative framing accuracy, inference latency, memory footprint, and implementation complexity to select the production detector for the frame cropping service.
- [ ] **Add Unit and Integration Tests in `eval/tests/`:** Provide hermetic tests for `eval_retrieval.py` metric calculations and query dataset parsing.

---

## 3. Dependencies & In-Scope vs Out-of-Scope

### 3.1 Dependencies
This workstream interfaces with and depends on the following components (owned by the Captain or other workstream owners; treat schemas as the interface):
- **Search API Contract (`contracts/search-contract-v1/`):** Owned by the Captain (see Section 4.1 below). Defines `POST /api/v1/incidents/search` request and response schemas.
- **Incident Contract Bump (`incident-contract-v3`):** Owned by the Captain. Extends report extraction items (`entities`, `instruments`, `assets`) with `timestamp_seconds` (integer) and text labels for detector grounding.
- **Search Endpoint Implementation:** `vss-agent` search route (`POST /api/v1/incidents/search`) deployed on the VM or mocked locally via `mock-backend/search_profile_mock/` (port 7778).
- **Video Storage & Pilot Data:** Surveillance video clips stored in Cloudflare R2 (`anomaly/` categories) and pilot test clips.

### 3.2 Out-of-Scope (Must NOT Touch)
- **Do not modify Search or Incident Contracts:** Schema changes in `contracts/` are owned by the Captain.
- **Do not modify Backend Search Route or Crop Service:** `services/agent/` search routes, VLM Critic loops, and `CropEvidenceService` are owned by the Captain.
- **Do not modify Database Migrations:** Supabase SQL migrations and RPC definitions (`supabase/migrations/`) are owned by the database workstream owner.
- **Do not modify Frontend UI:** `incident-console-v2/` search UI, cards, and video players are owned by the frontend workstream owner.

---

## 4. Interfaces & Technical Specifications

### 4.1 Search API Interface (`POST /api/v1/incidents/search`)

The retrieval evaluation script must interface with `POST /api/v1/incidents/search` adhering to `contracts/search-contract-v1`:

#### Request Schema:
```json
{
  "query": "string (1-500 chars, required)",
  "top_k": "integer (1-50, default: 10)",
  "min_similarity": "number (0.0-1.0, default: 0.2)",
  "item_types": ["entity", "instrument", "asset"],
  "filters": {
    "incident_types": ["string"],
    "min_severity": "integer (1-5)",
    "max_severity": "integer (1-5)"
  }
}
```

#### Response Structure:
```json
{
  "query_id": "string",
  "query": "string",
  "total_hits": "integer",
  "execution_time_ms": "number",
  "hits": [
    {
      "result_id": "string",
      "rank": "integer",
      "similarity_score": "number (0.0-1.0)",
      "item": {
        "item_type": "entity | instrument | asset",
        "item_id": "string (e.g. E1, I1, A1)",
        "name": "string",
        "description": "string",
        "threat_level": "integer | null",
        "holder_entity_id": "string | null",
        "crop_image_url": "string (uri)",
        "timestamp_seconds": "integer",
        "bounding_box": [ "ymin", "xmin", "ymax", "xmax" ]
      },
      "incident": {
        "incident_id": "string",
        "model_run_id": "string",
        "incident_type": "string",
        "severity_level": "integer (1-5)",
        "description": "string",
        "playback_url": "string (uri)",
        "incident_window": [ "start_sec", "end_sec" ]
      },
      "critic": {
        "verdict": "confirmed | rejected | unverified",
        "confidence": "number",
        "rationale": "string"
      }
    }
  ]
}
```

### 4.2 Retrieval Benchmark Metrics
`eval/scripts/eval_retrieval.py` must compute standard information retrieval metrics across the query dataset:
- **Precision@K:** Fraction of retrieved items in top-K that are relevant to the query intent.
- **Recall@K:** Fraction of total ground-truth relevant items for the query retrieved in top-K.
- **Mean Reciprocal Rank (MRR):** Reciprocal rank of the first relevant item ($1 / \text{rank}_1$) averaged across all queries.
- **F1 Score (@K):** Harmonic mean of Precision@K and Recall@K.
- **Critic Impact Analysis:** Metric comparison before vs after filtering or re-ranking by the VLM Critic's verdict (`confirmed` vs `rejected`).

### 4.3 Open-Vocabulary Detector Test Specification
The box-accuracy pilot demonstrated that general VLMs (Cosmos 3 Nano/Super, Nemotron Omni) fail spatial grounding (0% well-framed bounding boxes), but excel at temporal grounding (>95% timestamp accuracy).

For the detector evaluation:
- **Input:** Extracted RGB video frame at `timestamp_seconds`, conditioned on the item label (e.g. `"crowbar"`, `"handgun"`, `"silver hatchback"`, `"intruder"`).
- **Candidate Detectors:** Open-vocabulary 2D detectors such as Grounding DINO (`groundingdino-swint-ogc`), OWLv2 (`google/owlv2-base-patch16-ensemble`), and Florence-2 (`microsoft/Florence-2-large`).
- **Benchmark Video Set:** The 7 surveillance clips from the box pilot across distinct categories:
  1. `Animal003_x264.mp4` (Animal attack, 1448x948)
  2. `Assault007_x264.mp4` (ATM assault with weapon, 320x240)
  3. `Assault011_x264.mp4` (Street brawl with weapons/bikes, 320x240)
  4. `Burglary004_x264.mp4` (Vehicle crash into ATM & crowbars, 320x240)
  5. `Burglary010_x264.mp4` (Warehouse break-in with pry tools, 320x240)
  6. `RoadAccidents005_x264.mp4` (Night intersection crash, 320x240)
  7. `RoadAccidents010_x264.mp4` (Daytime vehicle collision, 320x240)
- **Evaluation Criteria:**
  - **Well-framed:** Bounding box tightly encapsulates the named object/person with minimal irrelevant background.
  - **Partly-framed:** Box captures part of the object or has excessive surrounding margin.
  - **Miss / Degenerate:** Empty frame region, full frame, or unrelated object.
  - **Inference Latency & Overhead:** CPU/GPU execution time per keyframe (<100ms target).

---

## 5. Open Questions & Decisions

1. **Benchmark Query Sourcing Strategy (Assignee Proposes):**
   - *Context:* Generating queries directly from `gt_incidents` descriptions was rejected by the Captain to prevent circular evaluation and artificial performance inflation.
   - *Options to evaluate:*
     - **Option A (Human Curation):** Domain operators / team members curate ~50 realistic natural language queries spanning broad situations, specific actors, instruments, and assets, manually assigning positive and negative ground-truth targets.
     - **Option B (LLM-Generated Variants with Human Review):** Generate 100+ query paraphrases and semantic distractors via LLM, followed by human manual validation of query-item relevance labels.
   - *Next Step:* Assignee recommends an option and defines the query schema file format (e.g., `eval/data/retrieval_benchmark_queries.json`).

2. **Detector Deployment Constraints (Coordinated with Captain):**
   - Whether the selected open-vocabulary detector will run inside the `vss-agent` Python environment on `kwanz-ws`, as a standalone microservice, or whether zero-GPU local environments fallback to full-frame keyframes when detector dependencies are absent.

---

## 6. Definition of Done

This workstream is complete when:
1. An independent retrieval benchmark query dataset is checked into `eval/data/`.
2. `eval/scripts/eval_retrieval.py` is implemented and can be executed via `uv run python scripts/eval_retrieval.py` against a running search endpoint, generating a Markdown and JSON summary of P@K, R@K, MRR, and F1.
3. Hermetic tests in `eval/tests/` verify metric computation and query dataset loading without requiring live network or DB access (`uv run pytest tests/`).
4. An empirical detector comparison report is documented in `eval/docs/` comparing candidate detectors on the pilot clips, recommending the optimal model for production frame cropping.
