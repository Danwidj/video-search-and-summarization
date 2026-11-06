# System evolution: NVIDIA VSS blueprint to the incident profile

Retrieved 2026-11-05, read-only, from `/home/hengz/vss-wt-c3e` at `2fa7529a6` (branch `eval/v2-c3e-evidence`, 18 commits ahead of `origin/main`, whose tip is #484). No model was called and `/home/hengz/evalv2-data` was not read.

Path shorthand: `P/` = `deploy/docker/developer-profiles/dev-profile-incident/`, `D/` = `P/.docs/`, `M/` = `P/eval/methodology/`, `X/` = `P/eval/docs/experiments/`, `FR` = `X/final-report.md`, `dec` = `D/decisions.md` (cited by entry date).

## 0. How to read this

### Evidence grades used in every "(3) Measured" point

| Grade | Meaning |
|---|---|
| **A** | Pre-registered, paired, on the 55 test clips. These clips were held out from selection but are **not unseen** (FR §11) |
| **B** | Development split (25 clips), controlled comparison or paired stage difference |
| **C** | Ad-hoc scout or small pilot. Mostly known only through the decision log; several raw reports sit outside the repo |
| **D** | Cost, latency or diagnostic measurement. It describes the system and is not a test of an improvement |

An absolute score with no before/after is reported as a level, never as an improvement. "NONE" means no experiment isolated the component.

### Caveats that apply to every accuracy figure

- `ground-truth-v1.0` is AI-assisted adjudication, frozen on dataset-level approval and not individually human-verified (FR header, §13).
- τ = 0.40 item matching is AI-calibrated and not human-validated. Item F1 reaches the floor at τ = 0.75 (FR §6.6).
- Evaluation V2 references are AI- or rule-generated and Human-unverified (dec 2026-11-03).
- Temperature 0 is not deterministic on this gateway. Per-clip swings of ±0.3 occur under identical requests (FR §10).
- V1 scope: one model (Cosmos 3 Super); crops, RP1 and persistence off; local agent, not the production VM (FR §3, §13).
- V2 Track B is the **historical** profile at agent `acbf892ba` (2026-11-01): person and object tracking off. It is not current production (`M/evaluation-v2-preregistration.md` line 243).

### Feature state at `2fa7529a6`

| Feature | Code default | VM default | Evaluated? |
|---|---|---|---|
| Zoomed second look | On (`INCIDENT_ZOOM_NAMES_ENABLED`) | On | Dev only (Track B); a C3 effect is pre-registered, result not in repo |
| Caption pass | **Off** | On since 2026-11-01 (#399) | Isolated effect **not available** |
| Person tracking | **Off** | On since 2026-10-31 (#397) | **Not evaluated** for accuracy |
| Object tracking | **Off** | On since 2026-11-02 (#458) | **Not evaluated**; scouts only |
| Set-of-marks | **Off** | **Off**, not set on the shared agent | **Not evaluated**; one run, live check open (status item 13) |
| Grounded chat | **Off** (template is default) | **Off**; merged, not deployed | Dev pilot; C3 numbers not in repo |
| Search critic | **Off** since 2026-10-28 | **Off** | **Not evaluated**; Track R not run |
| V1 severity prompt | Not adopted | Not adopted | Yes; no held-out gain |
| Ask for a chart | Built | **Activation pending**: VM needs a pull and restart (status item 12) | Yes, C3 scored |
| Privacy blur | **Removed** 2026-11-02 (#453) | Removed | Never evaluated |
| Contract v5 | Only on `origin/mvp3` | Not merged | No |

Defaults reach the shared agent only at its next restart (`D/status.md` §6), and the tracking and caption defaults live in `P/.scripts/native-services.sh` lines 131-139.

## 1. Original VSS vs our customised VSS

**(1) What changed.**
- **Stock:** NIM-hosted Cosmos3 Nano Reasoner and Nemotron-Nano-9B-v2, real-time video intelligence, downstream analytics, and an MCP top-level agent, with five reference workflows: Q&A and report, alert verification, real-time alerts, video search, long-video summarisation (root `README.md`).
- **Kept as is:** the NAT agent, tool registry and `chart_generator` core; the perception stack (NvStreamer, DeepStream RT-DETR with NvDCF, Kafka, Logstash, Elasticsearch, video-analytics API); Phoenix (`D/architecture.md`, "Stock VSS and What the Team Added").
- **Added:** eight `api/incident_*.py` route modules, the `incident_report_gen` tool, vendored `incident_contract/`, incident utilities, `incident-console-v2`, `vlm-gateway`, `contracts/`, `supabase/`, `eval/`, `start.sh`.
- **Not started:** NIM containers, VIOS/VST, HAProxy, Redis, SDR controller, stock web UI.
- **Dropped from MVP2:** multi-subagent routing and RT-CV / RT-Embed indexing (dec 2026-10-24).
- **Stock UI and evaluation are unused:** team console and team `eval/`, not `nat eval` (dec 2026-09-24).
- **Milestones:** profile skeleton and Streamlit console 2026-09-06 (`4836a1bcd`); hexagonal console 2026-10-20 (#120); revisions 2026-10-23 (#175, #177); VST off the upload path 2026-10-31 (#381); shadcn 2026-10-28 to 30 (#247 to #272, merged #280).

**(2) Why.** The goal is reviewable, versioned, structured incident reports rather than a general video agent (`D/action-plan.md` §1). Stock files are touched only to register or configure, so the fork stays mergeable. VST specifically cost a 100-camera cap, HTTP 415 on phone files and a double upload (dec 2026-10-31).

**(3) Measured.** Improvement: **NONE.** The measured result is **parity**, not advantage:
- [A] VSS − direct, base prompt: ΔI −0.007 [−0.036, +0.024]. V1 prompt: +0.023 [−0.003, +0.050] (FR §6.1).
- [A] VSS overhead 0.01 s p50, ≤ 0.05 s p95, with crops, RP1 and persistence off (FR §7).
- FR §14 lists "VSS extracts better than a direct VLM" as **not defensible**. VSS adds nothing before extraction, and sends the same request.

**(4) Architectural, no direct evidence.** Traceability, review workflow, the separable team code, the ports-and-adapters console, and mergeability with upstream.

## 2. Model hosting and inference architecture

**(1) What changed.**
- On-prem GPU NIMs retired for remote OpenAI-compatible endpoints: Brev Switchyard, `_type: openai`, bare base URLs (dec 2026-09-25).
- Roles at `D/status.md` §6: `LLM_NAME` `nvidia/nemotron-3-ultra`, `VLM_NAME` `nvidia/cosmos-3-super-reasoner`.
- RP1 model `nvidia/nemotron-3-nano-30b-a3b`; three-model allowlist of Cosmos 3 Nano, Cosmos 3 Super, Nemotron 3 Nano Omni (`P/contracts/inference.json`).
- Console default Nano, agent default Super (dec 2026-11-01).
- Embeddings: remote `nvidia/llama-nemotron-embed-vl-1b-v2`, 1024-d (dec 2026-10-18).
- `vss-agent` runs natively; appliances stay in Docker (dec 2026-09-21). Everything is pinned to GPU 0 (dec 2026-10-19).
- `vlm-gateway` holds the key server-side. Since 2026-11-02 vm mode starts no gateway (#459); gateway mode exists for the mock's own tests.
- OpenRouter (Gemma 4 31B, Qwen3.5-9B) is an evaluation arm only, not production.

**(2) Why.** The NGC free tier capped at 16 concurrent requests and hung report generation; `_type: nim` leaked `verify_ssl` and caused HTTP 400; Cosmos rejects tool calling on Brev, so it cannot be the LLM (dec 2026-09-25). Another user's job fills GPU 1 (dec 2026-10-19). The Brev key gets 403 on embeddings and older embedders are end-of-life (dec 2026-10-18).

**(3) Measured.** Improvement from the hosting change: **NONE**, since no local-vs-remote experiment exists. Related levels:
- [B] Model comparison as served, not hosting: contract validity Nano 48/50, Super 49/50, Omni 26/50, Qwen 38/50, Gemma 24/50. Entity F1 Nano − Super **−0.44 [−0.61, −0.04]** (`M/v2-dev-pilot-results.md` §3).
- [D] Earlier contract-v2 benchmark, 55 clips: type Nano 70.9%, Super 91.7%, Omni 43.5% (`P/eval/docs/vlm_benchmark_results.md`). Not comparable with later versions (`D/mvp2/eval.md` §1.1).
- [B] Chart transport change, gateway to agent: 74/75 items identical, 0.88 vs 0.87 (`M/v2-dashboard-change-assessment.md`). This shows no regression, not a gain.
- [D] Cost of remote dependence: Stage 1 lost 34 of 100 video-runs; the ~100 s ceiling is the main failure cause (FR §8). Super returned 524 in every health round from r5 to r13 (`M/v2-c3-contingency-a5-proposal.md` §1).

**(4) Architectural, no direct evidence.** Freeing the GPU for perception, keys held server-side, ~2 s native restarts. A local-NIM baseline does not exist, so "remote is better" is not a measured claim.

## 3. Incident extraction pipeline

**(1) What changed.** Before contracts, three paths differed in prompt, schema, taxonomy, video encoding and parsing. P1-v1 used few-shot examples, base64 video and lenient parsing (`P/eval/docs/vlm_benchmark_results.md`).

| Version | Date, ref | Change |
|---|---|---|
| v1 | 2026-09-27, `799d3d08b` | Shared `contracts/`: nested snake_case, strict schema, 5-label taxonomy, timeline, null confidence, no few-shot, strict parse |
| v2 | 2026-09-27, `24cf1438e` | `incident.duration` removed and derived in code; strict timeline rule |
| Policy `core-scored-v1` | 2026-09-27, #111 (`adb70795b`), no version bump | Only database-backed fields decide; `TIMELINE_*` becomes recorded enrichment |
| `id-normalization-v1` | 2026-09-27 console; mirrored in the agent #117 | Only repair: IDs, holder references, order. Refuses if free text would be affected; invariance-checked; eval never credits it |
| v3 | 2026-10-16, #114, #117 | Adds `timestamp_seconds` and `label` per item, for evidence |
| Single source | 2026-10-21, #155 | `.txt` prompts, `sync.py` drift check, vendored agent copy |
| v4 | 2026-10-23, #176 | Adds `first_seen_seconds` and `last_seen_seconds`, advisory |
| v5 | `origin/mvp3` only | Not merged; one strict-mode check would fail (status item 17) |

- **Append-only revisions** (dec 2026-10-23; #175, #177): `kind='ai'` or `kind='human'`, a trigger rejects UPDATE and DELETE, regeneration is a new branch with `parent_id` NULL, and `videos.official_revision_id` is an explicit choice. Exceptions are the video cascade and `apply_r2_rename` (`D/data.md`).
- **Attempt record:** four outcomes in immutable `model_runs.notes`; failures are never reports (`D/analysis-schema.md` §3-4).
- **Additions:** one retry for runaway output (`59619c733`, 2026-10-31), video-bounds rules (2026-10-25), run provenance (#422), request goldens (#416).

**(2) Why.** The benchmark was not measuring production (dec 2026-09-27). Category few-shot leaked the label. Cross-field rules can only be checked after decoding. Cosmos models emit lead-up events outside their own window. v3 exists because VLM boxes failed (area 5). v4 was added for a per-entity bar (dec 2026-10-23). JSONB snapshots replaced a design that could keep only one reviewer version.

**(3) Measured.** v1 to v4: **NONE**, as no experiment compares contract versions, and the docs say results across them are not comparable.
- [C] `core-scored-v1`: strict timeline rule rejected 7 answers, 4 with windows matching ground truth; recovered answers rose **6 of 15 to 13 of 15** (dec 2026-09-27). The entry says "12-call pilot" and "of 15" without reconciling them. This counts accepted answers, not accuracy.
- `id-normalization-v1`: rate of use **UNAVAILABLE**. No published figure was found.
- Runaway retry: explicitly unmeasured (dec 2026-10-31).
- Append-only revisions: **NONE**.
- [A] Level, not improvement: Stage 3 had 2 invalid outputs in 220 video-runs (FR §8).

**(4) Architectural, no direct evidence.** One contract across three consumers, the immutable attempt record, ID-only repair preventing silent semantic change, the explicit official pointer, provenance and goldens for reproducibility.

## 4. Captioning and long-video handling

**(1) What changed.**
- **Stock:** a separate LVS workflow chunks video and aggregates dense captions (root `README.md`).
- **Team, #386 (2026-10-31):** `utils/chunk_captions.py`. 20 s windows, 2 s overlap; clips ≤ 30 s not chunked; at most 4 calls in flight; same model as P1; stock caption prompts copied, because those tools are bound to VST.
- Captions go to P1 as one context message telling the model to trust the video. Prompt file, settings and schema are unchanged.
- **Display built then removed:** caption timeline #389, removed with alert rules #400 (2026-11-01). Captions are neither returned, stored nor shown.
- **Default:** on for VM #399; off in code. Experiment path via #436 and #439.

**(2) Why.** Sparse whole-clip sampling missed short events. In the scout, a fall at 82 s on a 94 s clip was read as "two people kneel", severity 1 (dec 2026-10-31). Stock tools were not reusable once VST and the NAT object store were out of the path.

**(3) Measured.** Isolated caption effect: **NONE available.**
- [C] Scout on the demo clip: captions gave "man falls and is assisted" with a correct 80-85 s timeline. This is qualitative, one clip, and captions also invented detail (a second man "also trips", a "robot vacuum cleaner").
- [D] Cost: about 28k prompt tokens and 3.3 calls per minute of 480p video, 5-8 s wall time, roughly triple the VLM tokens (dec 2026-10-31).
- [D] Dev Track B caption tokens per run: Super 24,016 of 67,678; Nano 11,681 of 37,715 (`M/results/v2-dev/track_b_pipeline.csv`). Ran on 14/25 Nano and 13/24 Super runs.
- The pre-registered caption effect (Track B raw P1 minus Track A P1, prereg line 156) has **no result in the repo: UNAVAILABLE**.
- **Do not quote** Super entity F1 0.61 (Track A) against 0.51 (Track B P1) as a caption effect. They are different runs and denominators, and the difference points the wrong way for the claim.

**(4) Architectural, no direct evidence.** Better long-clip recall. Time and calls with the full stack on are not measured (`D/incident-profile-operations.md`). A clip over about 3 minutes can exceed the 300 s model timeout (status §1). The empty-window filter is a wording heuristic. Frame-sampling behaviour itself is disputed (§13, item 1).

## 5. Grounding and evidence generation

**(1) What changed.**

| Step | Date, ref | Change | State |
|---|---|---|---|
| VLM boxes rejected | 2026-10-16 | VLM gives time and label, a separate stage gives boxes | Standing |
| Crop service | #127, #138 | `DefaultDetector` is **the remote VLM** with a grounding prompt, not a local detector | Standing |
| Whole-frame evidence | 2026-10-31, #377 | Store frame plus box; retry +1, −1, +2, −2 s; unfound is `located: false`, never a fake full-frame box. Crop kept only for search | On |
| Zoomed second look | 2026-10-31, #385 | Two blind looks, code-side agreement, text merge; applies at confidence ≥ 0.7; never changes id, label, times, or entity type | On |
| Person tracking | #387, #388, #397 | Stock perception per clip, IoU ≥ 0.3 within 0.5 s association, `-track.json` | VM on, code off |
| Object tracking | `e87c162fc`, #454 to #458 | Seeded OpenCV tracker (NanoTrack, Vit, then MIL), detector re-anchor every 2.5 s, budget 80, 120 s cap | VM on, code off |
| Set-of-marks | `5680baaa4` | Numbered person tracks drawn on the clip P1 sees | **Off** |
| Screen-person fix | 2026-11-02, `46500c0a0` | Grounding returns null for screens or reflections; tracks confirm person boxes | On, full live check open (16a) |
| Track time base | 2026-11-03, `97a7fb9b3` | Sample time = `frame_id / fps`; no box replaced from another moment | On, re-analysis open (16b) |
| First-seen image | 2026-11-03, #463 | Tracked item's image is its first track sample, replacing largest-box | On |
| Reviewer box tool | #465, #467, #468 | Draw, AI describes, tracker follows; replaced Replace image | Built; live proxy check open |
| Privacy blur | #401, #407, #412, #450 | Per-video face blur, then re-blur | **Removed** by #453 on 2026-11-02 |

Crops were 25-117 px on 480p clips. Note: `D/mvp2/eval.md` §11 itself records that using VLM boxes conflicts with "VLM boxes rejected". The rejected thing is boxes from the P1 extraction call. Do not call the production stage an "open-vocabulary detector" without this qualifier.

**(2) Why.** A whole-clip pass names items from low-resolution frames: a bag at 25 px became "soccer ball". Whole-frame context replaced magnified slices and fake boxes. One timestamped frame says nothing of duration. DeepStream is closed-vocabulary, so objects need another path. Blur was removed for cost with insufficient benefit: a whole-frame head search and 2.5 minutes to re-blur a four-item report (dec 2026-11-02).

**(3) Measured.**
- [C] VLM boxes 0% well-framed, timestamps over 95% accurate (dec 2026-10-16). The pilot report is outside the repo (`D/mvp2/eval.md` §1.1). No matched "after" figure exists on the same measure.
- [B] **Zoom is the only stage measured in isolation.** Paired by run, entity F1: **Super +0.026, Nano about 0**, no CI published (`M/v2-dev-pilot-results.md` §4).
  - Stage table in `track_b_pipeline.csv`, `p1_agent` to `final`, pooled: entities Super 0.5138 to 0.5688, Nano 0.1946 to 0.2282; **assets fell** Super 0.422 to 0.4037, Nano 0.3894 to 0.3717; instruments unchanged. Pooled and paired figures differ, so cite the paired one.
  - Severity and timing identical, as designed. Zoom cost per run: Super 19,508 tokens, Nano 7,773.
- [C] Tracker choice: NanoTrack 6/6 seeds against MIL 4/6; **74% vs 60%** of reference points on target; 3.9 vs 24 ms per update, three clips (dec 2026-11-02). Raw reports are outside the repo (`firstmate/data/...`).
- [D] Track time base: 5 of 6 wrong person boxes in revisions 115-124 traced to the old time base (dec 2026-11-03). Diagnostic; no after-rate.
- [C] Screen-person prompt: on stored IMG_8206 frames, no box at the TV frame, control still boxed, men boxed at 82 s and 84 s; one clip, not a full run (dec 2026-11-02).
- [C] Set-of-marks: 4 of 4 matched, but four entities reported for two men. The flag stays off (dec 2026-11-01).
- [B] Level only, C3-E dev, AI-referenced: correct evidence Nano 20/36 = **0.56** [0.37, 0.74], Super 20/35 = **0.57** [0.38, 0.76]; median IoU 0.74 and 0.81; temporal alignment 0.83 and 0.88. No Nano-Super difference (+0.06 [−0.11, +0.25]) (`M/c3e-dev-results-v1.md` §3). Over all matched entries 0.34 and 0.37. Tracking off, so this says nothing about tracking, the screen fix or first-seen images.
- [D] Reliability: Super located 150/150; Nano left 111/346 with no verdict at the 40-call cap. Cropping is 33-34% of request time (FR §7).
- Whole-frame evidence, person tracking accuracy, object tracking in production, first-seen image, blur: **NONE**.

**(4) Architectural, no direct evidence.** Reviewer usefulness of frame over crop, track-based presence bars, track confirmation of boxes, reviewer correction loop. Track D (detector comparison) did not run. C3-E evaluation half waits on Track B.

## 6. Prompt engineering evolution

**(1) What changed.**
- **Extraction:** few-shot P1-v1, then field-meaning only with schema-enforced output (2026-09-27), then per-item time and label (v3), then seen span (v4). The production prompt has not changed since #176.
- **Experiment:** append-only registry (#221). V1-V7 each add one block to `p1-v4-base`; V8 combines them. D9 v2 rule pre-registered on 2026-10-27.
- **Other prompts:** grounding null rule, blind zoom looks and merges, `zoom/describe-box`, chat prompts revised for prose over ids, chart prompt generated from the allowlist.
- **Governance:** `contracts/prompts/` with pinned SHA-256 (#418); request goldens (#416).

**(2) Why.** Few-shot leaked the label. Severity over-rating in Stage 1 (ground-truth level 3 predicted as 4 or 5 in 24 of 38 outputs) motivated V1 (FR §4). Scattered literals had no version to record (dec 2026-11-01).

**(3) Measured.** Prompt engineering is the best-evidenced area, and the held-out result is negative.
- [B] V1 selected on dev: ΔI **+0.051 [+0.013, +0.089]**, the only interval excluding zero of eight (FR §5.1).
- [A] Held out, VSS: **+0.019 [−0.015, +0.055]**, not confirmed. Direct arm: **−0.011 [−0.045, +0.024]** (FR §6.1).
- [A] Direct-arm description regression: −0.130 [−0.245, −0.018], one of about 40 intervals, not primary (FR §6.1).
- [B] Severity MAE on dev: 1.082 to 0.860, paired −0.220 [−0.380, −0.080], but signed error rose +0.18 to +0.42, so V1 did not fix the over-rating (FR §5.2). [A] On test: −0.038 [−0.189, +0.113] (FR §6.3).
- [B] V8 combined: +0.022 [−0.025, +0.071], V8 − V1 −0.016 [−0.054, +0.021] (FR §5.1).
- [C] Timeline wording changed nothing in a 12-call pilot (`D/analysis-schema.md` §7). [C] Blind zoom beat name-carrying zoom on IMG_9170: the model confirmed "soccer ball" at 0.7 and 0.9, while blind it said "black bag" (dec 2026-10-31).
- **V1 is not adopted.** Production prompt unchanged (FR §14).

**(4) Architectural, no direct evidence.** Prompt registry and goldens as change control; grounded chat prompt revisions; grounding null rule beyond one clip; few-shot removal, since few-shot prompting is untested in this design (FR §13, R4).

## 7. Object identification

**(1) What changed.**
- Reports list entities (`E#`), instruments (`I#`, holder, threat 1-5) and assets (`A#`), each with a label and second since v3.
- Names corrected after extraction by the zoom look, kept with `name_before` (#385).
- Reviewer box describe: an enlarged close-up, Nano first, then the main model, reasoning off (dec 2026-11-03).
- Scoring: one-to-one matching, τ moved 0.75 to 0.40 (v1.2).

**(2) Why.** Thumbnail-resolution extraction misnames small items. A reviewer boxing a white bottle got "floor tile", because beside the whole frame the model names the most prominent thing (dec 2026-11-03). τ = 0.75 pinned F1 near 0.01, a measurement fault rather than a model one (FR §4).

**(3) Measured.**
- [B] V1, object F1: +0.047 [+0.014, +0.084] on dev (FR §5.1). [A] On test the object component is +0.040 inside VSS and −0.001 direct, with no interval in FR, and ΔI is unconfirmed (FR §6.1).
- [B] Assets: V3, V4, V6 and V7 roughly halved false positives from 196 with recall held (FR §5.3). V8 asset F1 +0.059 [+0.011, +0.115], one of many intervals.
- [B] Zoom: see area 5 (Super entity +0.026 paired; assets fell in the pooled table).
- [B] Model effect: Nano − Super entity F1 −0.44 [−0.61, −0.04] (`M/v2-dev-pilot-results.md` §3).
- [A] Levels: entity F1 0.416-0.490, asset F1 0.219-0.294, instrument F1 0.065-0.267 on 1-4 matched instruments (FR §6.4). Instruments are too few for conclusions.
- Attribute correctness (names, descriptions, threat): **UNAVAILABLE** in the repo; dev pilot lists it as needing the judge.
- Box describe accuracy: qualitative only (bottle "better but not reliable"). **NONE.**

**(4) Architectural, no direct evidence.** That zoom improves reviewer trust in names; that reviewer boxes recover missed objects.

## 8. Chatbot querying (template vs grounded)

**(1) What changed.**
- **Stock:** a conversational `top_agent`; not used for incident chat.
- **Template, the default:** `POST /api/v1/incidents/chat`, `chat-contract-v1` (#130, 2026-10-16), console route #170, per-version answers #179. No model, no embedding. Rewritten as prose from the report (#435, 2026-11-01). Default search client now searches nothing.
- **Grounded (`INCIDENT_CHAT_MODE=grounded`, #428, #429, #430, 2026-11-02):** Nemotron 3 Ultra, strict schema, cited ids checked, `insufficient_evidence`, `chat-contract-v2`. Library questions use a checked plan; **counts are composed by code**, and a question the filters do not fully capture is refused.
- **Status: merged, OFF, not deployed.** It needs Evaluation V2 validation, an approved restart and a console change (status item 16).
- **Search beside it:** one `semantic_search` (#244), pgvector over evidence and revision embeddings, critic off.

**(2) Why.** Template chat listed ids and evidence regardless of the question ("5 relevant item(s)... human (E1)") and served demo data as real, and it could not answer official or library questions (dec 2026-11-01). Models miscount past a few reports, and a dropped filter widens a count while looking exact (dec 2026-11-02).

**(3) Measured.** Template vs grounded: **NONE.** No experiment scored template mode, so no improvement can be attributed to moving to grounded.
- [B] Grounded level, dev, PROVISIONAL AI-judged, 70 questions, Ultra (`M/v2-chat-judged-results.md`). Oracle = ground-truth reports; system = C1b Super reports:

| Metric | Oracle | System |
|---|---|---|
| Exact-answer accuracy | 0.78 [0.65, 0.89] | 0.24 [0.14, 0.35] |
| Citation precision / recall | 1.00 / 0.64 | 0.95 / 0.40 |
| Retrieval R@5 | 0.74 [0.55, 0.91] | 0.42 [0.23, 0.61] |
| Unsupported claims | 2/46 = 0.04 | 1/33 = 0.03 |
| Contradiction with ground truth | 1/55 = 0.02 | **28/42 = 0.67** |

- The source reads the gap as "mostly" upstream report errors. That is a reading of a contrast, not an isolated cause. Fact recall has n = 5 per corpus; holder identification is not interpretable.
- C3 chat: status says corpora were scored and judged, but **numbers are not in the repo: UNAVAILABLE.** The system corpus there is labelled contingency (Nano grounding).
- Retrieval benchmark and critic ablation (Track R): **not run**. Only the metrics module landed (`D/mvp2/eval.md` §10).

**(4) Architectural, no direct evidence.** Code-composed counts, id checking, refusal behaviour as safety properties in production; template rewrite quality.

## 9. Dashboard functionality (Ask for a chart)

**(1) What changed.**
- Counting moved to official-else-newest, with six fixed displays and an official split (#390, 2026-10-31); forms varied (#398).
- **Ask for a chart** (#391, 2026-10-31): the model picks a strict allowlisted `ChartSpec`; code fetches the figures; stock `chart_generator` draws them. The model never sees a figure and its text never reaches the database or screen.
- Model read moved to the agent's own LLM (#459, 2026-11-03).
- Severity words normalised in code before the model reads them (#476, `chart-severity-words-v2`). Chart prompt bytes unchanged.

**(2) Why.** Finals had 0 official revisions, so official-only counting showed an empty dashboard. Real figures only: a closed spec makes this structural. Text-to-SQL was rejected because model output would reach the database. Stock VSS has no natural-language analytics over a relational database (dec 2026-10-31). Ultra refused synonyms literally.

**(3) Measured.**
- [A] Held-out C3: exact-spec **57/60 = 0.95**, figures **72/75 = 0.96**, **0 false acceptances, 3 false refusals** (`D/status.md` §1). This is a level. The two denominators differ, and the set is template-worded, so dev and test are not comparable (prereg line 242). Full report **UNAVAILABLE** in the repo.
- [B] #476 severity words, Ultra dev: RB2 0.88 to **0.92**, paired **+0.04 [−0.03, +0.11]**, McNemar p = 0.45, **not significant**. Supplement valid requests 0.75 to 1.00, +0.25 [0.00, +0.50], p = 0.25. False acceptances 0 in both. One changed request regressed (`M/v2-dashboard-change-assessment.md`).
- [B] Dev model comparison: Ultra 0.87 (65/75), Super 120B 0.96 (72/75), Nano 30B 0.84 (63/75); Super − Ultra +0.09 [0.01, 0.19]. Production stays on Ultra.
- [C] Private-agent check: chart medians 0.8-1.7 s; bar and pie matched a read-only recount of 12 reports, 0 official (status item 12).
- Dashboard counting change: **NONE** beyond a read-only match with `/library`.

**(4) Architectural, no direct evidence.** Allowlist as a safety boundary beyond the 75-request sets; the official split, covered by unit tests only because finals has no official report; usability of the fixed displays. **Off in practice until the shared agent is updated.**

## 10. Operational efficiency

**(1) What changed.** Native agent, one-command `start.sh`, VST/HAProxy/Redis removed, one upload straight to R2 (#381), H.264 conversion (#382), batch upload (#384), background jobs (#392), critic off (#244), per-stage provenance (#422), tracker and detector limits (#454 to #458), box describe tuning.

**(2) Why.** Slow rebuilds; a shared 100-camera cap and double uploads; undecodable phone files; analyses lost on tab close; a rate-limited critic; a detector stall tail.

**(3) Measured.**

| Change | Before | After | Grade, source |
|---|---|---|---|
| Object-tracker detector limit | 10-65 s per item; 11% of 320 calls took 60-130 s and 77% of detector time | Slowest of 26 calls 8.6 s; 47 s for five items | C, dec 2026-11-02 |
| Tracker update | MIL 24 ms | NanoTrack 3.9 ms | C, dec 2026-11-02 |
| Box describe, reasoning off | about 30 s | about 3 s | C, dec 2026-11-03 |
| Box describe, Nano first | 60-125 s or 524 | 1-3 s | C, dec 2026-11-03 |
| Search critic off | 10-30 s | After-figure **UNAVAILABLE** | D, dec 2026-10-28 |

Levels only:
- [A] VSS overhead 0.01 s p50 (FR §7).
- [D] End-to-end with cropping, no captions or tracking: p50 28.2-28.9 s; cropping 8.5-9.6 s; capped worst case 193 s (FR §7).
- [D] Person tracking console path: 24 s clip 56 s, 49 s clip 79 s, 94 s clip 132 s; about 7.6 GB on GPU 0 (dec 2026-10-31).
- [D] Dev Track B per run: Super 67,678 tokens, 101 / 205 s p50/p95; Nano 37,715 tokens, 64 / 229 s (`M/v2-dev-pilot-results.md` §6).
- [D] Spend: Gemma $0.0011 per run, Qwen $0.0022 per run; C3 $0.45 of $2.00 (status). The gateway's $0 is not the sponsor's real cost (FR §9).
- Retries added 5-13% attempts (FR §8).
- C3 efficiency report: script exists (`P/eval/scripts/v2_c3_efficiency.py`), **numbers UNAVAILABLE** in the repo.

**(4) Architectural, no direct evidence.** ~2 s restarts (stated, not benchmarked); VST removal; H.264 conversion; batch and background jobs; full-stack latency, which is explicitly not measured yet. From code, `CropCallBudget` is built only from experiment settings, so production grounding appears uncapped; a report like Explosion014's 101 items would cost a call each. Not documented, worth checking before stating either way.

## 11. Claims that are safe and unsafe for slides

**Safe:**
- Pre-registered prompt process with all versions and negative results (FR §14).
- VSS parity with direct calls under identical requests; cropping costs about a third of request time.
- V1 helped on dev and did not clearly generalise.
- C3 dashboard 0.95 / 0.96 with 0 false acceptances, against deterministic references.
- Zoom: small dev gain on Super entity F1, about none on Nano.

**Unsafe:**
- "VSS extracts better than a direct VLM."
- "Prompt engineering improved held-out accuracy."
- Any claim about unseen footage.
- "Captions improve accuracy" or "tracking improves evidence".
- "Grounded chat beats template".
- "Human ground truth" (see §13, item 5).
- Any C3-E result as held-out or production.

## 12. UNAVAILABLE

- C3 Track A, Track B, chat and efficiency numbers; A5 outputs (private, or in run data I was told not to read).
- C3 caption and zoom effects.
- C3-E evaluation half.
- `id-normalization-v1` usage rate.
- Template chat scores.
- Search latency after the critic change.
- Box-accuracy pilot report, tracker scout reports, chunk scout data (outside the repo; known only through `dec`).
- PR numbers for pre-PR direct commits (v1, v2, object tracking, set-of-marks, screen fix, frame-id fix): commit hashes are given instead.

## 13. Discrepancies to resolve before presenting

1. **Frame sampling, three accounts.** `D/analysis-schema.md` §7 and `inference.json`: Super ignores `num_frames`, Nano honours it, about 24 frames. dec 2026-10-31: Nano ignores it, fixed 2 fps capped at about 60. `M/v2-dev-pilot-results.md` §5 probes: Nano ignores it and **Super honours 64**. Open as status issue 15. FR §3 repeats the "Super samples about 24" account.
2. **`FR` §13 is stale:** it says the cropping-on end-to-end profile was not run, while its header and §7 report it ran on 2026-10-30.
3. **`D/status.md`:** header says as of 2026-11-02 but it records 2026-11-04 events; its Evaluation row still contains "no held-out (C3) result exists yet" and "No V2 model call ... has happened yet", alongside C3 dashboard scores. Use the latest statements only.
4. **Nano type accuracy in `M/v2-dev-pilot-results.md` §4 (0.84 to 0.91) is not a zoom gain.** The CSV's `p1_agent` row is already 0.913, equal to `final`, and zoom never changes type. My inference: 21/25 against 21/23, a denominator change.
5. **"Human ground truth":** `D/action-plan.md` goal 4 and `P/eval/README.md` use the phrase, while FR says AI-assisted and not individually human-verified. Use FR's wording.
6. **A5 status:** `M/v2-c3-contingency-a5-proposal.md` at this commit says not approved; status and `eval/v2-c3-amendment-a5:.../v2-c3-amendment-a5.md` say owner-approved on 2026-11-04. Super gate holds until 2026-11-06 09:00 SGT, so C3 Super results may yet change.
7. **Checkout mismatch:** `/home/hengz/video-search-and-summarization` is on `main` at `ae7dd8554` (#407), behind `origin/main` (#484). That tree still contains privacy blur, which `origin/main` removed in #453. Do not demo or cite blur as current.
8. **`core-scored-v1` pilot size:** "12-call pilot" and "6 of 15 to 13 of 15" in the same entry.

## 14. Scope of this retrieval

Read in full: `FR`, `D/status.md`, `D/action-plan.md`, `D/analysis-schema.md`, `P/README.md`, `P/AGENTS.md`, and the V2 results (`M/v2-dev-pilot-results.md`, `M/c3e-dev-results-v1.md`, `M/v2-chat-judged-results.md`, `M/v2-dashboard-change-assessment.md`, A5 proposal). Read in part: `D/architecture.md` (through the gateway-mode runtime view), `D/decisions.md` (entries relevant to these areas), `D/data.md` (report model), `D/mvp2/*`, root and Docker READMEs. `services/agent` was reviewed by inventory, docs and targeted greps, not line by line.
