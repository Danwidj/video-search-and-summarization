# Ground Truth Refinement and Prompt Experiments: Plan

> **Status (2026-10-27): approved plan. PR 0 is done (offline scoring by default, the stashed benchmark work recovered, the Complete workbook gitignored). PR 2 is done (80 clips fetched and verified, `dataset-manifest-v1`, `_demo` resolution, split keys refreshed). PR 1A is done: [`annotation-guidelines-v1.0`](../../eval/ground_truth/annotation-guidelines-v1.0.md) is approved (scales unchanged, decision rules added, A1-A14 decided). PR 1B is done: [`evaluation-methodology-v1.0`](../../eval/methodology/evaluation-methodology-v1.0.md) (pinned scorer, scoring failures never become zeros, out-of-taxonomy Option C). PR 3 is done: [`audit-v0.1`](../../eval/ground_truth/review/audit-v0.1.md) and the review workbook `Ground Truth Review v0.1.xlsx`. PR 4 is done: [candidate v0.2](../../eval/ground_truth/review/candidate-v0.2.md) (86 verified corrections applied; 98 AI video-review proposals Pending human review; D5 settled as option (d), see `decisions.md`). PR 5 tooling is done: [freeze](../../eval/ground_truth/freeze/README.md) builds the `ground-truth-v1.0` candidate and freezes it only against an approval record; the freeze itself waits for approval of the final annotations and exclusions (and D7). PR 6A is done: the [registry](../../contracts/experiments/README.md) and the [runner](../../eval/experiments/README.md) (D13 (a), D14 (b) implemented). PR 6B is done: gated [experimental `/analyze` settings](../vm-api-contracts.md#experimental-settings-prompt-experiments-pr-6b) in the agent. PR 7 follows its approval gates.**

Two research questions, both treated as hypotheses:
- **RQ1:** does iterative prompt engineering improve VSS structured incident extraction?
- **RQ2:** how does the best development-selected VSS prompt compare with a fixed direct-VLM baseline?

Decision already taken (2026-10-27): `anomaly/demo/` in R2 is a presentation-demo storage location only. For evaluation its clips are ordinary videos (`<Id>_x264_demo.mp4` maps to `<Id>`), and the split ignores the folder.


## A. Current-state audit (verified 2026-10-27, read-only)

### A.1 What exists

| Area | State | Where |
|---|---|---|
| Contract and prompts | One version at a time: `incident-contract-v4` (P1 prompt, RP1 prompt, strict schema, `inference.json`). `sync.py` vendors 5 files into the agent. eval, the console and the agent each load fixed file names. Earlier prompt versions exist only in git history (v2 `24cf1438e`, v3 `54d0ae60f`, v4 `8b9f8967d`) and in `archived/` (P1-v1 few-shot) | `contracts/`, `eval/contract.py:41-75`, console `src/modules/contract/infrastructure/loader.ts`, `services/agent/.../incident_contract/__init__.py` |
| Prompt fingerprint | Only the console records `promptSha256`/`schemaSha256`. eval and the agent record only the `VERSION` string | `run-contract-analysis.ts:276` |
| P1 benchmark | `eval/scripts/eval_run.py`: split → signed R2 URL → P1 (temperature 0, 64 frames, strict `response_format`) → `contract.evaluate_policy` (`core-scored-v1`) → persist → score → results JSON plus an immutable `results/runs/<ts>/` copy | `eval/` |
| Scoring | Type and severity exact match; start/end/duration within ±5 s plus MAE; description by LLM judge (≥ 0.5); items by 1-to-1 Hungarian matching on MiniLM cosine ≥ 0.75, then P/R/F1 pooled over the run; matched instruments also scored for threat level (exact) and holder (correct/incorrect/unresolved); entity type exact. No blended score and no confidence intervals | `eval/eval_gt.py`, `eval/matching.py`, `eval/scripts/eval_aggregate.py`, `eval/config.py` |
| Database coupling | Scoring reads GT and predictions back **through a DB handle**, and matching writes `*_matches`. `eval_run.get_db()` and `eval_ingest_gt` call `db.get_db()`, which runs `init_schema()` and would **recreate the dropped tables on finals**. There is no offline mode, but the tests already score on SQLite (`tests/conftest.py`, `test_eval_gt.py:210`) | `eval/db.py:393,1209` |
| Uncommitted work | **`git stash@{0}`** ("WIP: incident evaluation benchmark changes", base `82e2223dc`, which is not in main) and commit `65cb7f1cb` (its untracked files). They add `--incident-only`, per-call latency, 429/Retry-After pacing, `failure_kind` and `classify_outcome()`, rotating model order, judge-call counting, an empty description scored 0 without the judge, `eval_benchmark_export.py` and `eval_dataset_stats.py`. **Every current result file came from this code** | `git stash show stash@{0}` |
| Results | One v2-era run (2026-10-02): 3 models × 55 videos, incident fields only. Severity exact accuracy 22-27% for all three models; type accuracy 44-92%; 16/165 requests failed (mostly 429) | `eval/eval_data/results/` (gitignored) |
| Splits | Seed 42, per category: 5 former few-shot clips (now simply excluded) and the rest for evaluation, 25 + 55 = 80 in total. There is no dev/test distinction. Manifests store **pre-move R2 keys**: 24 now point to objects that no longer exist | `eval/eval_reproducibility/split_*.json` |
| Ground truth | `Complete Ground Truth Labelling.xlsx` (profile root, sha `7c3f1fcc186e…`, **untracked and not gitignored**). The scripts read the older `eval/eval_data/ground_truth_labelling.xlsx` (sha `502eeefa…`). Both hold the same 80 incidents (15-18 per category); Complete adds 9 duplicate `_demo` rows and 1 instrument (Burglary041 I1) | profile root, `eval/eval_data/` |
| GT contents | 80 incidents, 169 entities, 33 instruments (only 13 within the 55-video evaluation list), 96 assets. Timestamps are integer seconds; 4 annotators; severity distribution 1:9, 2:25, 3:31, 4:13, 5:2; threat levels 1:13, 2:1, 3:17, 4:2. The workbook Severity Guide matches the prompt rubric almost word for word | |
| R2 | `anomaly/` without `shooting/`: 80 clips, 1.15 GB. `demo/` has 24 clips (moved from the category folders, sizes identical); the other 56 are in 5 category folders. Every clip has exactly one GT incident. Max 333 s, mean 62 s | bucket `anomaly-detection-dataset` |
| What "VSS" does today | `POST /api/v1/incidents/{id}/analyze` (`services/agent/.../api/incident_analyze.py`, `tools/incident_report_gen.py`) builds a P1 body **identical to eval's direct call**: the same `extraction_prompt()` file, the same `inference.json` P1 settings, the same strict `response_format`, the same signed URL and therefore the same frame sampling. Its only per-request text is `reviewer_prompt` (≤ 1000 characters, appended as a hint). It then adds: video-bounds validation, optional RP1 (`skip_rp1`), post-P1 evidence cropping (one remote-VLM box call per item, up to 4 attempts, R2 upload when configured), and best-effort persistence (`model_runs` and `report_revisions`), which is skipped when Supabase is not configured. There is **no perception, tool calling or subagent stage** (Track F was dropped 2026-10-24). The response has no P1-only timing and no token usage (eval.md §7) | agent code |
| Video AI | Only the Switchyard gateway can see video: `cosmos-3-nano-reasoner`, `cosmos-3-super-reasoner`, `nemotron-3-nano-omni`. It takes signed URLs and samples about 24-64 frames; Super ignores `num_frames`. NVIDIA, OpenAI and Anthropic keys are empty or absent. Judge variables (`INCIDENT_LLM_*`, `INCIDENT_JUDGE_MODEL`) are unset | `.env.local` (names only) |
| Local tooling | ffmpeg is **not installed**. 930 GB free. The eval venv has boto3 but no cv2 or av. Frame utilities exist in the console (ffmpeg) and the agent (OpenCV) | |
| Tests and CI | eval hermetic suite: 254 passed, 1 skipped. **No CI exists**; all checks run locally | |

### A.2 Gaps and risks found

1. **Database coupling:** scoring cannot run without a DB, and the DB path can recreate retired tables on finals.
2. **Judge:** not versioned or recorded, no temperature setting, its env is unconfigured, and HEAD sends empty descriptions to it.
3. **Embeddings:** the health check (`127.0.0.1:8811`) and the actual calls (`INCIDENT_EMBEDDING_BASE_URL`) can hit different servers. A mid-run embedding failure silently produces zero matches.
4. **Instrument scoring:** holder and threat level are scored only on matched instruments, with no rate metric. The held-out set has 13 instruments, so statistical power is very low.
5. **eval's validator:** no v4 cross-field rules (first/last seen). Thresholds are not recorded per run.
6. **Prompt identity:** no prompt hash in eval runs; the prompt can change without a `VERSION` bump.
7. **`eval_aggregate`:** crashes on `results/dataset_stats.json` (`KeyError: category`).
8. **Ground truth:**
   - 24 incident rows use `_demo` filenames while their child-sheet rows use plain names.
   - 9 incidents are duplicated.
   - Holder `'E4 '` has a trailing space (Burglary009 I1).
   - About 15 rows have stray cells.
   - Vague or out-of-rule instrument names: "object", "red item", "weapon", "suv", "chair".
   - 35 entity Image cells hold Google Drive URLs. These are informational, not errors.
   - The ingest docstring wrongly says dates are Excel serial numbers.
9. **Split manifests and finals:** the manifests and the finals `videos.filepath` for Assault018/030/032/036/050 point at moved R2 keys. The Supabase side is out of scope; it is recorded only.
10. **Uncommitted code:** stashed eval work is drifting from main and is the only code that reproduces the stored results.

### A.3 Reuse rather than rebuild

- **Validation and scoring:** `contract.evaluate_policy` with its fixtures; the pure scorers `compare_incident_fields`, `score_matched_pair`, `resolve_holder` and `prf1` (`eval_gt.py`); `matching.solve_assignment`.
- **Ground truth and results:** `eval_gt_schema.load_gt_index` (workbook to P1-shaped GT, no DB); `eval_video_resolution.resolve_filename` and `signed_url`; `write_results` with its immutable archive.
- **Aggregation:** `aggregate_one` and `pool_aggregates`; `retrieval_metrics.bootstrap_interval` (generic, seeded) and the `paired_difference` pattern.
- **R2 and video:** the R2 client `eval/r2_videos.client()`; `eval/video_duration.mp4_duration_seconds`.
- **The stash:** latency, pacing, outcome classification and benchmark export.

## B. Annotation and evaluation specification (PR 1A and 1B)

### B.1 Annotation guidelines `annotation-guidelines-v1.0`

A standalone document. It is not a prompt.

- **Starting points:**
  - The P1 prompt's definitions (incident, entities, instruments, assets, classification rule, general rules).
  - The workbook Severity Guide, which already matches the prompt rubric.
- **What it adds:**
  - **Severity decision rules:** observed harm vs potential danger; tie-break rules between adjacent levels; a worked example per level and per category from the GT.
  - **Threat level:** potential harm, not outcome. It reconciles the one difference: the workbook lists "bag" at level 1.
  - **Significance rules:** participants, victims, responders/interveners, bystanders, background. Visibility alone is never enough.
  - **Instrument vs asset:** the hand-held test, with examples taken from the audit ("suv", "hose", "fuel nozzle", "chair").
  - **Description templates:**
    - Incident: what happened, who, key action, observable outcome (1-3 sentences).
    - Entity: type, distinguishing appearance, role/action.
    - Item: name, appearance, relevance.
  - **Uncertainty and partial visibility:** use hedged-but-objective wording; never invent attributes.
  - **GT visual grounding:** image and bounding-box fields are intentionally empty; no screenshots and no boxes. Representative-frame `timestamp_seconds` and `label` are VSS output fields and are not scored.
- **Kept separate from:** the GT-correction prompt (PR 4) and the VSS experiment prompts (PR 6). Each cites the guideline version it implements.

### B.2 Evaluation methodology `evaluation-methodology-v1.0`

Keeps the existing method where it is sound, fixes the defects, and records every constant in each result.

| Field | Rule (proposed) |
|---|---|
| type | Exact match after `canonical_incident_type` (unchanged) |
| severity | Exact match (primary). Secondary: within ±1, signed bias (over/under), 5×5 confusion matrix |
| start / end | Within ±5 s (unchanged) plus MAE. Duration is derived and reported, not a separate criterion |
| incident description | Pinned LLM judge: fixed model id, `judge-prompt-v1` text in a file, temperature 0, recorded per result. Pass at ≥ 0.5. An empty prediction scores 0 with no judge call. Secondary: deterministic MiniLM cosine, so judge drift can be detected |
| entities / instruments / assets | 1-to-1 Hungarian matching on MiniLM-L6-v2 cosine ≥ 0.75 (unchanged). Embedded text: `"type description"` for entities, `"name description"` for instruments and assets. TP = matched pairs, FP = unmatched predictions, FN = unmatched GT. P/R/F1 pooled per run (primary) and the per-video mean (secondary). Threshold sensitivity at 0.65 and 0.85 is reported but never used for selection |
| entity attributes | Type exact; description judged, on matched pairs |
| instrument attributes | Threat level exact (primary) and within ±1, on matched pairs. **Holder accuracy** = correct / (correct + incorrect) on matched instruments whose GT holder is an entity; unresolved cases are counted separately. Counts are always shown next to rates because the sample is small |
| asset attributes | Name and description judged, on matched pairs |
| empty arrays | Both sides empty: no TP/FP/FN (excluded from per-video means, count reported). GT empty and prediction not: every prediction is an FP |
| nulls | GT holder null: excluded from holder accuracy. `confidence_score` is not scored |
| invalid output (`contract_failed`, parse failure, `core_ok=false`) | Counted as a **model miss**: empty prediction, every field wrong, GT items become FN. The rate is reported |
| API/infra failure (429, timeout, HTTP/gateway error) | **Not** a model miss. Retried with pacing (from the stash). A video still failing is excluded from **both** arms of a paired comparison and counted |
| aggregation | Field accuracy over videos. Per category, and overall both micro (video-weighted) and macro (category mean). No single blended score in reports. A selection index is defined separately (decision D9) |
| uncertainty | 95% cluster bootstrap over videos (`bootstrap_interval`, fixed seed). Prompt comparisons are paired per video |
| excluded from scoring | title, severity_reason, location, timeline, uncertainties, confidence_score, per-item `timestamp_seconds`, `first/last_seen_seconds`, `label`, image, bounding_box, RP1 prose |
| recorded per result | methodology version, GT version, guideline version, prompt id and sha256, schema sha, contract version, model and params, judge model and prompt version, embedding model and URL, thresholds, git SHA, split id, video ids, latency, token usage, outcome class, timestamps |

Reference fixtures (hand-built GT and prediction pairs with expected scores) pin every row above in hermetic tests.

## C. Dataset preparation (PR 2)

- **Source:** `anomaly/{demo,animal_attacks,assault,burglary,explosion,road_accidents}/`, excluding `shooting/`. That is 80 clips, about 1.15 GB.
- **Clip identity:** `<Id>_x264[_demo].mp4` maps to incident id `<Id>`. The original R2 filename is preserved exactly on disk.
- **Download:** to `eval/eval_data/videos/<r2 folder>/<filename>` (gitignored), using the existing `eval/r2_videos.client()`. Files land as `.part`, are renamed after verification, and a rerun skips files whose size and sha256 already match (resumable). Retries use backoff.
- **Integrity:**
  - size equals the R2 `ContentLength`;
  - MD5 equals the ETag for single-part uploads (multipart ETags are noted, not compared);
  - local sha256 recorded;
  - MP4 header duration parsed;
  - duplicate content detected by sha256 across keys;
  - zero-byte files and folder markers (`anomaly/demo/`) skipped and reported.
- **Manifest:** `eval/eval_reproducibility/dataset-manifest-v1.json` (tracked, contains no video). Per clip: key, filename, incident id, category, demo flag, size, ETag, sha256, duration, R2 LastModified. Plus totals and a manifest sha.
- **Is a local copy needed?** VSS runs and VLM correction use signed URLs and do not need it. Local copies are needed for hashing, frame and contact-sheet extraction for human review and frame-based correction, and offline duration checks. 1.15 GB against 930 GB free makes this cheap.
- **Also in this PR:**
  - a `_demo`-aware `resolve_filename`;
  - regenerated split manifests with current keys (same membership);
  - a profile-root `.gitignore` rule for `*.xlsx`, so the untracked GT workbook cannot be committed by accident.

## D. Ground-truth correction (PR 3 audit, PR 4 AI-assisted correction)

- **PR 3 audit (read-only):**
  - Mechanical checks on the workbook, all listed in §G.
  - Heuristic flags for the guideline rules: vague names, non-hand-held instruments, speculative wording lexicon ("appears to be the owner", "probably"), description length outliers, entities without role words.
  - Video-to-workbook matching against the PR 2 manifest.
  - Output: machine-readable findings plus a committed summary report with ids only.
- **PR 4 correction:** for each video, an AI reviewer receives:
  1. The original human annotation for that video, from the audited workbook.
  2. `annotation-guidelines-v1.0`.
  3. Video evidence, in the form chosen under decision D5.
  4. The PR 3 findings for that video.

  It returns structured **proposals**: field, original, proposed, explanation, evidence timestamps, confidence, or "uncertain". It never returns a rewritten workbook.
- **Long videos:** the full clip by signed URL (24-64 frames is too coarse beyond about 120 s), plus dense sampling (1-2 fps) over the annotated incident window ±10 s, and sparse sampling (0.2 fps) elsewhere. This catches omitted items outside the window and boundary errors. Frame timestamps are burned into each frame so evidence can be cited.
- **Independence, enforced by code and tests:**
  - The correction pipeline must not read `eval_data/results/`, experiment prompts, VSS predictions or scores.
  - The correction prompt lives in `eval/ground_truth/correction_prompts/`, not in `contracts/`.
  - A test asserts the input builder cannot reach those paths.
- **Traceability:**
  - An append-only change log (JSONL plus an xlsx review view) with: `change_id`, filename, incident id, sheet, record id, field, original, proposed, explanation, evidence timestamps and frame refs, model id and params, correction prompt version and sha, guideline version, `review_status` (pending / accepted / rejected / modified / uncertain), reviewer, accepted value, reviewed_at.
  - The corrected dataset is **generated** from the original workbook plus the accepted log entries. The original is never edited.
- **Human review:**
  - 100% review of high-impact proposals: type, severity, threat, added or removed items, relationships, ambiguous classifications, unsupported descriptions.
  - Description-only edits reviewed on a sample (see D6).
  - Blind review of a stratified sample of **unchanged** incidents (at least 20%) to find missed errors.
  - A second reviewer on at least 20% of incidents for severity and threat, with Cohen's κ reported.
  - Anything still undecided keeps an `uncertain` flag rather than a forced answer.

## E. Ground-truth freezing (PR 5)

- **`ground-truth-v1.0`:**
  - Normalised JSON (incidents, entities, instruments, assets, plus per-row `review_notes` and `uncertain`, which are not scored).
  - `MANIFEST.json` with the sha256 of every artifact: source workbook, corrected workbook, change log, review record, guideline version, methodology version, dataset manifest, split.
  - A README.
- **Loader:** `load_gt_index(version=…)` reads the frozen JSON, verifies checksums, and refuses a mismatch.
- **Freeze rules** (as in the brief): no label changes to help VSS; a genuine error means `v1.1` plus a rerun of every compared prompt version; reference answers are never exposed to VSS prompts.
- **Split (recommended):** reuse the existing seeded partition as `split-v2`:
  - **dev** = the 25 former few-shot clips (5 per category);
  - **test** = the 55 evaluation clips;
  - same membership, fixed keys, `_demo` mapped.

  Why: it is already fixed and seeded, and no clip of the 80 is unexposed (see §F.5). The 25 were embedded verbatim as few-shot demonstrations in the retired P1-v1 prompt, so they are the weaker test candidates. The 55 were exposed through evaluation and pilots, not by being placed in a prompt. Trade-offs: a 25-video dev set gives wide confidence intervals, and instruments are thin, so instrument findings are reported descriptively. The held-out set is **not pristine**; §F.5 assesses the leakage and its consequences. Alternatives are listed under D8. Related-video leakage: UCF-Crime clips are independent recordings; the frozen manifest also records a perceptual-hash near-duplicate check across splits.

## F. Prompt experimentation and the direct-VLM vs VSS comparison (PR 6 infrastructure, PR 7 execution)

### F.1 The two arms

| | Direct VLM | VSS |
|---|---|---|
| Path | Harness → Switchyard `/v1/chat/completions`, through `eval_vlm_client.analyze_video_with_p1` (today's eval path) | Harness → vss-agent `POST /api/v1/incidents/{id}/analyze` → the same upstream |
| Model | `nvidia/cosmos-3-super-reasoner` (primary; D10) | The same model, passed as the request `model` |
| Video input | Signed R2 URL; the gateway samples frames (about 24 for Super, which ignores `num_frames`) | The same signed URL and settings, so the same sampling |
| Prompt | `p1-v4-base` (fixed baseline), and in Stage 3 the selected optimised prompt | `p1-v4-base`, then the registry variants |
| Post-processing | None | Bounds check (MP4 header), RP1 skipped (`skip_rp1: true`), persistence off. **Cropping off for every accuracy run**; on only in the separate end-to-end profile (§F.2, D14) |
| Scored output | Raw P1 content → `eval.contract.evaluate_policy` → the frozen scorer | Raw P1 content from the 200 response, or `raw_output` from a 422 → the **same** `evaluate_policy` and scorer (Track X rule, eval.md §4). The agent's own acceptance decision is recorded but never replaces `core-scored-v1` |
| Latency | P1 inference wall clock (harness host) | (i) the agent-reported P1-only time; (ii) end-to-end `/analyze` wall clock |

**Prompt effects vs pipeline effects:**
- With the same model, the same input frames and the same prompt, the two arms send the **same P1 extraction request**. Today's VSS adds nothing before extraction; its additions (bounds check, cropping, RP1, persistence) all run after P1 and do not change the extracted fields.
- **Pipeline effect** = VSS minus direct VLM at the **same prompt**. It is expected to be near zero. A non-zero value can only come from upstream non-determinism, transport, retry or timeout behaviour, or failure handling. It is reported as a pipeline/reliability difference, **never as an architectural extraction advantage**. Claiming one would need evidence of a relevant architectural difference before extraction, which current VSS does not have. (If VSS gains pre-extraction stages, such as perception or tool use, that becomes a new configuration and the claim can be tested. That is Track F, out of scope.)
- **Prompt-engineering effect** = optimised minus baseline prompt **within the same arm**. It is measured in both arms, so a prompt gain can be shown to hold independently of the pipeline.
- A large equal-prompt gap is treated as a defect signal (harness, transport, validation) and investigated before it is reported.

**Common evaluation representation:** the `incident-contract-v4` P1 JSON. Both arms are re-validated by eval's `evaluate_policy` and scored by the same frozen scorer, ground-truth version and split. If D13 picks a baseline prompt with a different output shape, it must still return the v4 schema via `response_format`, or the comparison is invalid.

### F.2 Stages

**Stage 0: plumbing, pilot and budget approval (before any full-scale inference)**
1. **Plumbing on mocks** (no paid calls): both arms against the :7777 mock or a fake transport; check results are complete and re-scorable.
2. **Paid pilot**, only after explicit approval of its own small budget:
   - 5 dev videos (1 per category) × 2 arms × `p1-v4-base` × N 1, which is 10 P1 calls plus about 50 judge calls;
   - plus 2 videos through VSS with cropping on, about 2 P1 and 10-40 box calls.
   - Measures: tokens per call, latency, 429 rate, judge-call count, equal-prompt parity on real calls, and the cost of a crop call.
3. **Budget statement:** per-stage call counts and token and cost estimates extrapolated from the pilot's measured figures.
4. **Explicit approval gate:** the user approves the Stage 1 budget, recorded in `decisions.md`. Stages 2 and 3 each get their own budget approval before they start.
- Pilot results are reported separately and **never used for prompt selection or in the final comparisons**.

**Stage 1: baselines (dev set only)**
1. **Fixed direct-VLM baseline:** run N times (D10) on the dev videos. Raw outputs, parsed outputs, scores, config, prompt text and sha are saved under `results/experiments/direct-vlm-baseline/` and **frozen**.
2. **Initial VSS baseline:** `p1-v4-base` through the agent, with the same videos, N, model and scorer.
3. **Report:** both arms and their paired difference (the pipeline-effect parity check), reliability, and inference latency. Cropping is off, so there is no end-to-end figure here.

**Stage 2: VSS prompt engineering (dev only)**
- Variants E1-E7 (below) run **only through the VSS arm**.
- The direct-VLM baseline is **not rerun**. Its saved raw outputs are reused, and are re-scored offline (no inference) only if the GT or methodology version changes. That requires a documented new GT version and re-scoring of every arm.
- Each variant is compared paired against the **initial VSS baseline** (primary, for RQ1) and against the saved direct-VLM baseline (secondary, for context).
- All versions are kept, regressions included. The best variant is chosen by the pre-registered rule (D9), not by recency, and recorded in `decisions.md` before Stage 3.

**Stage 3: final held-out comparison (test set, accuracy run once, cropping off)**
- **Four mandatory configurations** on the same 55 test videos, frozen ground truth and scorer:

  | # | Configuration | Arm | Prompt |
  |---|---|---|---|
  | C1 | Direct-VLM baseline | direct | `p1-v4-base` |
  | C2 | VSS baseline | VSS | `p1-v4-base` |
  | C3 | Optimised VSS | VSS | the dev-selected prompt |
  | C4 | Optimised direct VLM | direct | the dev-selected prompt (byte-identical text and sha to C3) |

- **The four required paired comparisons** (per video, 95% cluster-bootstrap CIs, on the same video set):

  | Comparison | Measures | Answers |
  |---|---|---|
  | C2 − C1: VSS baseline vs direct-VLM baseline | Pipeline effect at the baseline prompt | Parity / reliability |
  | C3 − C2: optimised VSS vs VSS baseline | Prompt-engineering effect inside VSS | **RQ1** |
  | C4 − C1: optimised direct VLM vs direct-VLM baseline | Prompt-engineering effect without VSS | Whether the prompt gain transfers independently of the pipeline |
  | C3 − C4: optimised VSS vs optimised direct VLM | Pipeline effect at the optimised prompt | **RQ2**, attributed |

- **RQ2 as originally phrased** (C3 − C1, best VSS vs the fixed direct baseline) is also reported, explicitly decomposed as (C3 − C4) + (C4 − C1), that is pipeline effect plus prompt effect. It is never presented as a VSS architecture advantage.
- **Reported dimensions:** incident fields; entity, instrument and asset P/R/F1 plus attributes; **inference** latency (p50/p95, same host); reliability and failure classes per configuration.

**Separate end-to-end pipeline profile (cropping on; latency and reliability only)**
- After Stage 3, run C2 and C3 through VSS with cropping on, on a fixed subset of 15 test videos (3 per category), N = 1. That is about 30 `/analyze` calls plus crop calls (about 30 × items × 1-4 attempts).
- It measures end-to-end `/analyze` latency vs agent-reported P1-only time, crop-stage time, crop failures and image gaps, and end-to-end reliability.
- Its extraction outputs are **not** used for accuracy. A 6B test proves extraction fields are identical with crops on and off for the same raw output.
- Inference and end-to-end figures appear in separate tables and are never mixed.
- **No prompt changes after test results.** The runner's test guard logs the single test execution, and any rerun needs a documented reason (infrastructure failure only).

### F.3 Registry, runner and experiments

- **Registry:**
  - `contracts/experiments/p1/<prompt-id>.txt`, immutable, plus `contracts/experiments/registry.json`. Each entry records: id, parent, sha256, contract/schema version (fixed at `incident-contract-v4`, so scoring stays comparable), guideline version, hypothesis, created date, status.
  - Ids: `p1-v4-base` (byte-identical to today's `incident_extraction_prompt.txt`), then `p1-v4-e01-severity`, `p1-v4-e02-entities`, and so on.
  - The production prompt, `sync.py`, the console and the agent are **not changed**. Adopting a winner in production is a separate later decision with a contract bump.
- **Tests:** every registry sha matches its file (immutability); the base sha equals the production prompt; ids are unique; a parent exists.
- **Experiment config:** `eval/experiments/configs/<exp-id>.json` with: **arm** (`direct-vlm` | `vss`), prompt id, model, inference params, pipeline options (cropping, `skip_rp1`, agent base URL and git SHA, host), GT version, methodology version, split, repeats, budget cap, and for VSS configs a `baseline_ref` naming the saved direct-VLM run to compare against.
- **Runner:** `eval_run.py` gains `--experiment`, which drives arm, prompt, GT version and split.
  - It refuses `--split test` unless the config is marked final and names a selection record in `decisions.md`.
  - It refuses to rerun a frozen baseline (it re-scores saved outputs instead).
  - The `vss` arm transport implements the Track X response handling (eval.md §4).
- **Results:** `eval_data/results/experiments/<exp-id>/<ts>/` (gitignored, immutable). The committed report goes to `eval/docs/experiments/`.
- **Experiments** (Stage 2, VSS arm only, dev only), each with a written hypothesis and one prompt component changed at a time:
  - E1 severity decision rules (observed harm vs potential danger);
  - E2 entity significance and bystander exclusion;
  - E3 instrument hand-held rule, instrument vs asset, and threat assignment;
  - E4 asset relevance and background exclusion;
  - E5 description templates;
  - E6 few-shot examples (dev-set clips only, chosen across categories so the label does not leak, as happened with P1-v1);
  - E7 structured self-consistency checklist and uncertainty handling.

  The improvements are then combined into one candidate.
- **Workflow:** the brief's 13 steps, mapped onto Stages 1-3 (§F.2).
- **Analysis outputs, per configuration:**
  - overall, per field and per category tables;
  - severity confusion matrices;
  - threat errors;
  - FP/FN by item type;
  - latency (inference and end-to-end kept separate) and tokens;
  - failure analysis by class and arm;
  - qualitative examples of improvements and regressions.

### F.4 Fairness and reproducibility rules

- **Same everything that is not under test:** guideline version, methodology version, ground-truth version, split, video set, model and model version, inference parameters, and representation (v4 JSON through one validator and scorer).
- **Recorded per configuration:** arm, model and version, full prompt text and sha, parameters, pipeline components and switches, agent git SHA and host, harness git SHA, Switchyard base URL (no keys), frame-sampling behaviour as documented (Super ignores `num_frames`), timestamps.
- **Preprocessing:** both arms send the same signed URL, and the gateway does the sampling, so preprocessing is identical today. Any arm-specific preprocessing added later must be reported as a difference.
- **Latency:**
  - **Inference latency** (P1 call: wall clock for direct, agent-reported P1-only time for VSS) comes from the accuracy runs.
  - **End-to-end pipeline latency** comes only from the separate cropping-on profile.
  - Both are measured from the same harness host, and they are never mixed in one table or one difference.
- **Cost separation:** accuracy experiments never pay for cropping. Box calls happen only in the Stage 0 pilot (2 videos) and the end-to-end profile (15 videos × 2 configs).
- **Same underlying model:** yes, both arms use Cosmos 3 Super. This controls for model capability. Because today's VSS adds no pre-extraction processing, equal-prompt differences are expected to be small. That is the parity finding, not evidence for or against VSS architecture.
- **Role of the three allowlisted models:**
  - `cosmos-3-super` is the **only** model used for development, selection and the primary Stage 3 comparison.
  - `cosmos-3-nano` and `nemotron-3-nano-omni` are an **optional transfer check** in Stage 3 on the direct arm only (C1 and C4, since the pipeline adds nothing before extraction), reported separately and never used for selection.
- **No outcome is assumed:** VSS may tie or lose to direct VLM, and prompt variants may regress. Every result is reported.

### F.5 Held-out set exposure and leakage assessment

The proposed 55-video held-out set is **not unseen**. Documented exposure:

| Exposure | Evidence | What leaked |
|---|---|---|
| Earlier VLM benchmark (2026-10-02, contract v2, 3 models × 55, incident fields) | `eval/eval_data/results/`, the `benchmark/` exports; headline figures in this plan §A.1 | Per-video predictions, per-field scores and failure patterns on the 55, against the *pre-correction* ground truth, visible to the team |
| Contract and prompt design pilots | `.docs/analysis-schema.md` §7 names Animal003, Assault018 and Burglary005 (all held-out) in the 12-call timeline pilot behind `core-scored-v1` and the v3 timeline wording (`decisions.md` 2026-09-27, 2026-10-16) | The baseline prompt `p1-v4-base` was partly shaped by observing behaviour on held-out clips |
| Other pilots (box accuracy 2026-10-16; the 2-clip RP1 pilot) | `decisions.md`; the clips used are not recorded | Unknown: treat as possible held-out exposure |
| Ground-truth correction (PR 4) | Planned: covers all 80 clips | Labels are revised on test clips too. That is legitimate (it is independent of VSS) as long as the correction never sees VSS predictions or scores (the PR 4 independence guard blocks `eval_data/results/`) |
| The dev alternative (25 former few-shot clips) | Embedded verbatim in the retired P1-v1 prompt | Stronger exposure, so these are kept as dev, not test |

**Consequences for the final results:**
- **Within-arm prompt comparisons (C3 − C2, C4 − C1): the direction of any bias is uncertain.** Mechanisms pull both ways, and none can be measured with the data available:
  - *Towards the baseline:* `p1-v4-base` was partly shaped on held-out clips (the timeline pilot), while optimised prompts are developed on dev only. That alone would understate prompt-engineering gains.
  - *Towards the optimised prompt:* the people writing Stage 2 prompts have already seen per-video results and failure patterns on the 55. Quarantining the files does not remove what the team remembers, so that knowledge can shape "dev-only" prompts and overstate gains.
  - *Size unknown:* the documented baseline fitting concerned timeline wording, which is not scored. Ground-truth correction (PR 4) also changes the reference after all exposures, which may weaken or redirect any earlier fitting.
  - The report therefore treats C3 − C2 and C4 − C1 on test as **possibly biased in either direction**. It does not claim they are conservative.
- **Equal-prompt pipeline comparisons (C2 − C1, C3 − C4):** both sides use the same prompt with the same exposure, so prompt exposure creates no *differential* bias between them. Shared limitations (the same ground truth, the same clips) still apply.
- **Absolute accuracy levels** on the test set may be biased in either direction and are reported as such. They are **not comparable** with the 2026-10-02 figures (different contract version, pre-correction ground truth, unpinned judge).
- **External generalisation** is limited: the result describes these 80 UCF-Crime clips under this exposure history, not unseen footage.

**Mitigations:**
- **Quarantine:** Stage 2 prompt authors must not open per-video 2026-10-02 results or pilot outputs for test clips. The runner reads no `results/` from the test split during Stage 2, and the authors record that they complied.
- **Disclosure:** the final report includes this table, the mechanisms above, and the statement that the direction of bias is uncertain.
- **Optional sensitivity:** report C1-C4 also on the test clips not named in any recorded pilot (52 of 55). It is descriptive only.
- **Future work:** a truly unseen set needs new labelled clips (D8 note).

## G. Multi-PR roadmap

The brief's 7 PRs, plus a technical **PR 0**, with PR 1 split into **1A/1B** so guidelines and scoring can be reviewed independently. Both must be approved before PR 4.

| PR | Title | Depends on | Size |
|---|---|---|---|
| 0 | `fix(eval)`: recover stashed benchmark work; add a file-backed (no-DB) scoring path | – | M |
| 1A | `docs(eval)`: annotation-guidelines-v1.0 | – (approval gate) | M |
| 1B | `feat(eval)`: evaluation-methodology-v1.0, scorer fixes and reference fixtures | PR 0 | M-L |
| 2 | `feat(eval)`: R2 dataset fetch, integrity check and manifest | PR 0 (helpers) | M |
| 3 | `feat(eval)`: ground-truth workbook audit | 1A, 1B approved; PR 2 | M |
| 4 | `feat(eval)`: AI-assisted GT correction pipeline and review | PR 3; decisions D5-D7 | L |
| 5 | `feat(eval)`: freeze ground-truth-v1.0 and split-v2 | PR 4 reviewed and approved | S-M |
| 6A | `feat(eval)`: prompt registry, two-arm experiment runner, frozen-baseline reuse | PR 1B (built and tested hermetically); formal runs wait for PR 5 | M |
| 6B | `feat(agent)`: experiment hooks on `/analyze` (gated prompt id, crop switch, P1 timing, usage, raw output) | PR 6A registry format; D13, D14 | S-M |
| 7 | `docs(eval)`: Stage 0-3 runs, end-to-end profile and reports (several PRs: one per stage) | PR 5, PR 6A, PR 6B; D9-D11, D13-D15; budget approval per stage | L (mostly runs) |

**Why PR 6 is split.** 6B changes `services/agent`, a separate component with its own `AGENTS.md`, checks and deployment, and its API contract is documented in `vm-api-contracts.md`. Without it, the VSS arm cannot run any prompt other than the production one. `reviewer_prompt` is only an appended hint, so it is not a valid substitute. Keeping 6A and 6B separate keeps the eval PR hermetic, and lets the agent change be reviewed against both analysis modes.

Enforced dependencies:
- guidelines and scoring (1A, 1B) before correction (4);
- dataset integrity (2) before correction (4);
- reviewed correction (4) before freeze (5);
- freeze (5) before formal experiments (7);
- test evaluation only after selection, inside 7.

Parallel work: 0, 1A and 2 can start together, and 6A/6B can be built while 3-5 proceed.

**PR 0.**
- Objective: rebase the stash and `65cb7f1cb` onto main. Keep the eval code and tests; drop the stale docs hunks and rewrite them.
- Changes: `eval_run.py` scores from in-memory GT (`load_gt_index`) and the prediction dict through a file-backed provider with the same method surface as `IncidentDB` (`get_gt_incident`, `list_gt_*`, `get_incident`, `list_incident_*`, `record_*_match`). DB persistence becomes opt-in (`--persist-db`), and `init_schema()` is never called against a remote DSN.
- Also: fix `eval_aggregate` skipping non-result JSON; run the embedding health check on the same URL that is used; abort the run on an embedding failure.
- Tests: results JSON re-scoring is identical to the SQLite path for a fixture; a guard test proves no DSN means no DB access.
- Risks: stash merge conflicts with #199-#213; v2-era behaviour assumptions.

**PR 1A.**
- Files: `eval/ground_truth/annotation-guidelines-v1.0.md`; `.docs/decisions.md` entries for each approved definition.
- Acceptance: one authoritative definition set with examples and counterexamples; reviewed by the annotators.

**PR 1B.**
- Files:
  - `eval/methodology/evaluation-methodology-v1.0.md`
  - `eval/methodology/judge-prompt-v1.txt`
  - `eval/methodology/fixtures/*.json`
  - `eval/eval_gt.py`, `eval/scripts/eval_aggregate.py`, `eval/config.py`
  - tests
- Changes: pinned and recorded judge; empty description scores 0; holder-accuracy rate; severity within-1, bias and confusion; failure classes per §B.2; paired bootstrap (`bootstrap_interval`); run metadata (prompt sha via the same hashing as the console's `promptSha256`).
- Acceptance: the fixtures demonstrate every rule in §B.2; the full hermetic suite passes.

**PR 2.**
- Files: `eval/scripts/eval_fetch_videos.py`, `eval/dataset_manifest.py`, `eval/eval_reproducibility/dataset-manifest-v1.json`, `split_*.json` (keys refreshed), `eval_video_resolution.py` (`_demo`), `.gitignore`, the SKILL and the README.
- Tests: hermetic, with a fake S3 client: resume, retry, size/ETag mismatch, duplicates, zero-byte objects, `_demo` mapping.
- Acceptance: 80/80 verified, the manifest committed, and no credentials or video in git.

**PR 3.**
- Files: `eval/scripts/eval_gt_audit.py`; `eval/docs/ground-truth/audit-v1.md` (ids only); full findings in `eval_data/audit/`.
- Checks:
  - filename to manifest;
  - incident-row vs child-sheet filename (`_demo`);
  - duplicates;
  - E#/I#/A# format and sequence;
  - holder references (after trim);
  - type, severity and threat domains;
  - start < end, duration = end − start, and window within the video duration from the manifest;
  - missing or short descriptions;
  - stray cells;
  - guideline heuristics.
- Not flagged: empty images.
- Tests: synthetic workbook fixtures, one per check. The original workbook is opened read-only and its hash is verified before and after the audit.
- Acceptance: every issue is listed with a severity (error / warn / review).

**PR 4.**
- Files: `eval/ground_truth/correction_prompts/gt-correction-v1.0.txt`, `eval/scripts/gt_correct.py`, `eval/scripts/gt_review_export.py`, `eval/scripts/gt_apply_review.py`, frame tools (per D5), tests (independence guard, log schema, apply-review determinism).
- Deliverables: the proposed corrected dataset, the change log, the review workbook, review results and κ.
- Risks: a weak or same-family VLM proposing wrong edits (mitigated by human review); cost; 429s.

**PR 5.**
- Files: `eval/ground_truth/v1.0/*`, `eval/eval_reproducibility/split-v2.json`, loader changes, checksum tests, `.docs/decisions.md` approval record.
- Acceptance: `load_gt_index("v1.0")` verifies checksums, and the split is reproducible from its seed.

**PR 6A (eval).**
- Files:
  - `contracts/experiments/{registry.json,p1/*.txt}`, `contracts/README.md`;
  - `eval/contract.py` (`extraction_prompt(prompt_id=None)`; the default stays the production file);
  - `eval_run.py`/`eval_run_lib.py` (`--experiment`, arm transports `direct-vlm` and `vss`, frozen-baseline reuse and re-score, test-split guard, metadata per §F.4);
  - `eval/experiments/configs/` (including `direct-vlm-baseline.json`, `vss-baseline.json`);
  - the results layout `results/experiments/<config-id>/<ts>/`.
- Tests (all hermetic, fake transports):
  - registry immutability; the base sha equals the production prompt;
  - test-split guard; refusal to rerun a frozen baseline;
  - Track X response handling (200 / 422 with `raw_output` / transport failure → classes);
  - both arms produce the same scored representation for the same raw output;
  - completeness of the metadata record.
- Acceptance: a mock plumbing run of both arms produces complete, re-scorable results and the four-configuration (C1-C4) comparison table with all four paired comparisons from saved outputs. Accuracy configs default to `skip_crops: true`.

**PR 6B (agent).**
- Files: `services/agent/src/vss_agents/api/incident_analyze.py`, `tools/incident_report_gen.py`, `incident_contract/__init__.py`; `contracts/sync.py`, if experiment prompts are vendored (D14); agent tests; `.docs/vm-api-contracts.md`; the `incident-operate-vm` / `incident-analyze-video` skills.
- Changes:
  - **`experiment_prompt_id`:** honoured only when the env flag `INCIDENT_EXPERIMENTS_ENABLED=1` is set, and only for ids in the registry whose sha matches. It never changes the production default.
  - **`skip_crops`:** a new request switch to turn post-P1 cropping off.
  - **New response fields:** `p1_elapsed_ms`, `usage`, `raw_output` on a 200 response, plus the prompt id and sha actually used.
  - **Unchanged:** with the flag unset, behaviour is byte-identical.
- Tests:
  - flag off ignores or refuses the field;
  - unknown id or sha mismatch gives 400;
  - the P1 body equals eval's for the same prompt id (a parity test);
  - the timing and usage fields are present;
  - **extraction output is identical with `skip_crops` true and false** for the same upstream response (this justifies separating accuracy from the end-to-end profile);
  - `skip_crops` makes no box calls.
- Acceptance: the agent checks in `services/agent/AGENTS.md` pass, and the console works unchanged in both analysis modes.
- Risks: deploying to the shared VM is ask-first. Mitigation: run the experiment agent as a local instance with no Supabase env (persistence then skips) and no R2 env (crops are not uploaded). See D14.

**PR 7: Stage 0-3 runs and reports.**
- **7.0 Stage 0:**
  - plumbing on mocks;
  - **pilot budget approval**, then the paid pilot (§F.2);
  - `stage0-pilot.md` with measured tokens, latency, 429 rate and per-call cost;
  - the per-stage budget statement;
  - **explicit approval of the Stage 1 budget**, recorded in `decisions.md`.
- **7.1 Stage 1** (crops off):
  - the direct-VLM baseline and the VSS baseline on dev, N repeats;
  - freeze the direct-VLM baseline;
  - report `eval/docs/experiments/stage1-baselines.md`.
  - The Stage 2 budget is approved before Stage 2 starts.
- **7.2 Stage 2:**
  - E1-E7 and the combined candidate through the VSS arm on dev;
  - an experiment log of every version (hypothesis, diff from parent, paired results against the VSS baseline and against the frozen direct-VLM baseline, regressions);
  - a selection record in `decisions.md` per D9;
  - report `stage2-prompt-engineering.md`.
- **7.3 Stage 3** (after Stage 3 budget approval):
  - one held-out accuracy run of the **four mandatory configurations C1-C4**, crops off (plus the optional transfer models on C1/C4);
  - then the separate end-to-end profile (C2, C3; 15 test videos; crops on);
  - final report `final-report.md`.
- **Final report sections:**
  1. Research questions and answers, with paired effect sizes and 95% CIs, no outcome assumed.
  2. Configuration table (C1-C4): arm, model, prompt id and sha, pipeline switches, host, SHAs.
  3. Incident fields per configuration (type, severity exact, ±1 and bias, start/end ±5 s and MAE, description), with the **four paired comparisons**:
     - C2−C1 (pipeline at baseline);
     - C3−C2 (prompt in VSS, RQ1);
     - C4−C1 (prompt in direct);
     - C3−C4 (pipeline at optimised, RQ2 attributed);
     - plus C3−C1 shown as their decomposed sum.
  4. Entities, instruments and assets: P/R/F1 plus attributes (threat, holder), with counts, for the same four comparisons.
  5. Per-category tables and severity confusion matrices per configuration.
  6. **Inference latency** (C1-C4, p50/p95), and in a separate table **end-to-end pipeline latency** from the cropping profile (with the P1-only share and the crop stage), same host.
  7. Reliability: outcome classes per configuration (valid, contract-invalid, request_failed, timeout, 429, agent 422/5xx), and crop failures from the profile.
  8. Tokens and cost where available, split into accuracy runs vs the end-to-end profile.
  9. The Stage 2 history, including failed versions.
  10. Qualitative examples.
  11. **Prompt vs pipeline attribution** (§F.1): no architectural extraction advantage is claimed without evidence of a pre-extraction architectural difference.
  12. **Held-out exposure and leakage** (§F.5): the mechanisms, with the direction of bias stated as uncertain.
  13. Remaining systematic errors and limitations.
  14. Selected prompt and why.
- **Acceptance:**
  - both RQs answered from the frozen ground truth with all four paired comparisons and CIs;
  - all prompts, configs, raw outputs and scores preserved;
  - the test set was run once after selection, with the guard log attached;
  - the pilot and every stage budget were approved before they ran;
  - claims stay within §F.1, §F.4 and §F.5.
- **Adopting** the selected prompt into production is a separate decision with a contract bump. It is out of scope.

**Documentation in every PR**, per the docs rule:
- `.docs/status.md`, `.docs/decisions.md`, `.docs/mvp2/eval.md` (§1.1 points to the methodology), `eval/README.md`, `skills/incident-run-eval/SKILL.md` (new commands), `contracts/README.md` (PR 6A), `.docs/vm-api-contracts.md` and the agent-facing skills (PR 6B), and the README doc index.
- Six artifact types stay in separate folders, never conflated:
  - guidelines → `eval/ground_truth/`
  - correction prompts → `eval/ground_truth/correction_prompts/`
  - frozen GT → `eval/ground_truth/vX/`
  - experiment prompts → `contracts/experiments/`
  - methodology → `eval/methodology/`
  - results → `eval/docs/experiments/`
- No Supabase schema changes.

## H. Risks and open decisions

**Blocking decisions** (needed before the PR shown):

| # | Decision | Options | Recommendation | Needed by |
|---|---|---|---|---|
| D1 | Severity and threat definitions | (a) adopt the existing rubric as is; (b) rubric plus explicit tie-break rules and per-category examples | **(b)**: the wording stays the same, so earlier results remain interpretable | 1A |
| D2 | Significance rules and description format | (a) the prompt's current text; (b) plus templates and audit-derived examples | **(b)** | 1A |
| D3 | Description scoring | (a) LLM judge only; (b) pinned judge primary plus MiniLM cosine secondary; (c) embedding only | **(b)**. The judge model must be chosen: a fixed Switchyard text model (e.g. `nvidia/nemotron-3-nano-30b-a3b`, already used for RP1), temperature 0 | 1B |
| D4 | Matching threshold and aggregation | Keep 0.75 / ±5 s / pooled P/R/F1, or recalibrate | **Keep**, plus sensitivity tables. Calibrating on VSS output would couple scoring to the system under test | 1B |
| D5 | GT-correction model and video approach | (a) a Switchyard VLM on the full clip; (b) an external video-native frontier model (new key and dependency, cost); (c) a strong image model on sampled frames (needs a key plus ffmpeg or OpenCV); (d) Claude Code reviewing extracted frames interactively (no new key; less automated) | **(b) or (c) if a key is approved**, because they are independent of the VSS model family. Otherwise (a) with a model different from the experiments' primary model and 100% human review. ffmpeg or `opencv-python-headless` is a new dependency (ask first) | 4 |
| D6 | Human-review depth | High-impact 100% and others sampled; or 100% of everything | **High-impact 100%**, description edits ≥ 30% sampled, unchanged ≥ 20% blind, second reviewer ≥ 20% with κ | 4 |
| D7 | Frozen GT storage | (a) normalised JSON committed in git, workbooks gitignored with sha recorded; (b) everything gitignored plus checksums; (c) R2 `ground-truth/` prefix | **(a)**, plus (c) for the xlsx files after approval (an R2 write). Text describing public UCF-Crime clips; confirm the data licence allows committing | 5 |
| D8 | Dataset split | (a) reuse 25 dev / 55 test; (b) new stratified 30/50; (c) grouped 5-fold cross-validation for development plus a fixed test | **(a)** | 5 |
| D9 | VSS prompt selection rule (Stage 2) | (a) a single primary metric; (b) an equal-weight index of 8 field scores; (c) (b) with guardrails: no field drops with its CI below −5 pp, core-validity not lower | **(c)**, measured against the **initial VSS baseline**, pre-registered in `decisions.md` before the first dev run. The direct-VLM baseline is context only and does not enter selection | 7 |
| D10 | Models, repeats and the role of the three models | (a) Cosmos 3 Super only; (b) all 3 models throughout; (c) Super for everything that decides, the other two as an optional Stage 3 transfer check | **(c)**. N = 2 repeats on dev (non-determinism at temperature 0) and N = 2 on test, so run-to-run noise is visible | 7 |
| D11 | Budget, pilot and approval gates | Estimates in P1 calls, Super, 25 dev and 55 test videos, N = 2; judge ≈ 5 calls per scored video-run; accuracy runs make **no crop calls**. **Stage 0 pilot:** 10 P1 + ≈ 50 judge + 2 VSS-with-crops (≈ 10-40 box calls). **Stage 1:** 50 + 50 = 100 P1. **Stage 2:** ≈ 8 versions × 25 × 2 = 400 P1. **Stage 3 accuracy:** 4 configs × 55 × 2 = 440 P1. **End-to-end profile:** 30 `/analyze` + ≈ 150-600 box calls. Optional transfer: 2 models × 2 configs (C1, C4) × 55 = +220. **Judge:** ≈ 4,700 for the mandatory accuracy runs. **GT correction:** ≈ 80-160 VLM calls. 429 pacing is required. Token and cost figures are replaced by pilot measurements | The pilot runs under its own approved budget. Each later stage needs explicit approval of a pilot-based budget statement, recorded in `decisions.md`. A plumbing run on mocks comes first. No paid call happens before approval | 4, 7 |
| D13 | Direct-VLM baseline and comparison fairness | (a) same model + the same `p1-v4-base` prompt + v4 schema, called directly; (b) same model + a minimal generic prompt constrained to the v4 schema (confounds prompt and pipeline from Stage 1); (c) a different VLM called directly (confounds model choice) | **(a)**. **C4 (direct VLM + selected prompt) is mandatory** in Stage 3, so every difference is attributable: prompt effect = C3−C2 and C4−C1; pipeline effect = C2−C1 and C3−C4. If a naive-usage baseline is also wanted, add (b) as an extra frozen direct config rather than replacing (a). Approval also confirms the interpretation rule: no architectural extraction claim (§F.1) | 6A, 7 |
| D14 | How the VSS arm runs | Where: (a) the shared VM agent (deploy 6B, restart shared services: ask first; writes finals unless persistence is disabled); (b) **a local agent instance** at the same git SHA, no Supabase or R2 env, same Switchyard endpoint. Cropping: off for all accuracy runs (Stages 1-3); on only in the pilot and the separate 15-video end-to-end profile. Prompt delivery: read the registry from `contracts/experiments/` (repo checkout), or vendor it via `sync.py` | **(b)**, with crops off for accuracy and on only in the pilot and profile, and the registry read from the checkout behind the env flag. The VM figures, if wanted, are a separate labelled latency appendix | 6B, 7 |
| D15 | Held-out exposure handling | (a) accept the 55 as test with the disclosure, quarantine and optional sensitivity subset of §F.5; (b) swap: test = the 25 former few-shot clips (more exposed, smaller); (c) collect and label new unseen clips before Stage 3 (more time and labelling effort) | **(a)**, with the exposure mechanisms and the uncertain direction of bias stated in the final report. Plan (c) as future work if an unbiased absolute accuracy figure is needed | 5, 7 |
| D12 | Recover the stash | Rebase onto main vs reimplement | **Rebase** (PR 0) | 0 |

**Optional refinements:** a judge calibration set (about 20 human-scored pairs); threat within ±1 as a reported metric; per-item timestamp scoring (GT has none, so this would mean new labels); adding the 50 shooting clips as a future category (outside the contract taxonomy); recording latency and cost for RP1.

**Risks:**
- over-reading the VLM/VSS comparison: today's VSS sends the same P1 request as direct VLM, so a large equal-prompt gap would more likely indicate a harness, transport or validation defect than an architecture effect. Investigate before reporting it;
- small samples (instruments, a 25-video dev set) give wide confidence intervals;
- the correction AI shares the VSS model family (D5);
- Switchyard non-determinism at temperature 0 and 429s;
- the stash rebase;
- evaluator drift if the judge is not pinned;
- annotation leakage into prompts via few-shot examples (dev only);
- the untracked workbook being committed by accident (PR 2 `.gitignore`);
- the broken finals `videos.filepath` for 5 Assault clips (Supabase; out of scope; needs a separate decision).

## I. Recommended next steps

1. **First PR: PR 0.** It is technical, needs no methodological approval, unblocks offline scoring, removes the finals table-recreation hazard and stops the stash drifting.
2. In parallel: draft **PR 1A** (guidelines) for review, and settle D1-D4.
3. **PR 1B**, then **PR 2** (the 1.15 GB fetch after approval), then **PR 3**.
4. Settle D5-D7, then **PR 4**, human review, then **PR 5** (freeze), with **PR 6A/6B** built alongside once D13 and D14 are settled.
5. Settle D9-D11 and D15, then **PR 7**:
   1. Stage 0: mock plumbing → approved pilot → budget approval.
   2. Stage 1.
   3. Stage 2 (after budget approval) → selection record.
   4. Stage 3 C1-C4 accuracy, run once (after budget approval).
   5. The end-to-end profile.
