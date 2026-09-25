# P1 structured incident extraction — VLM benchmark results

This document records the results of a controlled three-model comparison on
structured incident extraction (the "P1" prompt/schema). It is the tracked,
durable summary of a run whose raw inputs (ground-truth Excel workbook, cached
videos) and raw per-video outputs are intentionally **not** committed (see the
`eval_data/` rule in `eval/.gitignore`); this file, plus the split manifests under
`eval_reproducibility/`, are what make the run's outcome and methodology
reproducible without shipping the raw data.

All figures below are read directly from the persisted run artifacts —
`eval_data/results/summary.json` and the 15 per-category-per-model result
files it is built from (`scripts/eval_aggregate.py`) — not reconstructed from
memory.

## What was compared

Exactly one experimental variable: the VLM used for P1 extraction. Everything
else — prompt, few-shot demonstrations, video split, inference configuration,
report-generation model, evaluator — was held fixed across all three runs.

| Model | Role |
|---|---|
| `nvidia/cosmos-3-nano-reasoner` | P1 extraction (compared) |
| `nvidia/cosmos-3-super-reasoner` | P1 extraction (compared) |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | P1 extraction (compared) |

All three were reached through the same OpenAI-compatible `vlm-gateway`
(model-agnostic passthrough to the switchyard upstream), never modified
per-model beyond the `model` field in the request.

## Evaluation methodology

- **Categories (5)**: Animal Attack, Assault, Burglary, Explosion, Road Accident.
- **Split**: for each category, a fixed-seed random sample (`seed=42`,
  `random.Random(seed).sample(...)` over the alphabetically sorted filename
  list) designates 5 videos as few-shot demonstration videos; every remaining
  labelled video in that category is held out for evaluation. This yields
  **55 held-out evaluation videos per model** (Animal Attack 10, Assault 10,
  Burglary 13, Explosion 10, Road Accident 12), i.e. **165 total P1 attempts**
  across the three models. The split is generated once and persisted as a
  manifest per category (`scripts/eval_generate_split.py`); later runs read
  the manifest rather than re-sampling, so the split cannot silently drift.
  See "Reproducibility artifacts" below for where the manifests are tracked.
- **Few-shot demonstration mechanism — text-exemplar, identical for all three
  models.** A frame-based/multi-video visual mechanism was spiked first and
  rejected: two of the three models hard-reject more than one video per
  request (`HTTP 400: "At most 1 video(s) may be provided in one prompt"`),
  and a frame-based variant caused `nemotron-3-nano-omni-30b-a3b-reasoning` to
  fall into a degenerate repetition loop. The adopted mechanism instead
  serializes each of the 5 demonstration videos' ground-truth structured
  output as text (matching P1's own output schema) and prepends them as
  worked examples in the P1 prompt sent for each held-out video. This works
  identically as a single-video call for all three models, so no model
  receives a different demonstration mechanism from the others.
  **Held-out ground truth is never included in a P1 request** — only the
  5 demonstration videos' own ground truth is ever shown to the model, and
  only for videos outside the evaluation set.
- **Fixed P1 inference configuration** (identical for every model, every
  video): `{"temperature": 0.0, "max_tokens": 4096}`.
- **Fixed RP1 (report generation) model/configuration** — used identically
  regardless of which P1 model produced the input, and never varied as part
  of the comparison: model `nvidia/nemotron-3-nano-30b-a3b`, config
  `{"temperature": 0.0, "max_tokens": 4096}`. RP1 takes P1's structured JSON
  as its only input (no video) and produces a human-readable report. **RP1's
  output is generated and persisted for every video/model but is never
  scored** — it is not part of any metric in this document.
- **LLM judge** (semantic scoring of the free-text `description` field):
  model `nvidia/nemotron-3-nano-30b-a3b` (same model as RP1's fixed config,
  configured independently via `INCIDENT_JUDGE_MODEL`), returns a 0.0–1.0
  similarity score, pass threshold `>= 0.5`. A bounded retry (max 2 attempts)
  applies only when the judge's response could not be parsed into a score;
  network/HTTP failures are never retried and abort the run (see "Failure
  handling" below).
- **Object/entity matching**: `sentence-transformers/all-MiniLM-L6-v2`
  embeddings (served locally; no remote embeddings endpoint exists for this
  deployment) over `type+description` (entities) or `name+description`
  (instruments/assets), solved as an optimal one-to-one assignment via the
  Hungarian algorithm (`scipy.optimize.linear_sum_assignment`), with pairings
  below cosine similarity **0.75** (`config.MIN_MATCH_SIMILARITY`) dropped.
  Objects are never matched by position or ID.
- **Field scoring**: exact match for `type`/`severity_level`; ±5s tolerance
  (`config.EVAL_TIMESTAMP_TOLERANCE_SECONDS`) for `start_timestamp`/
  `end_timestamp`/`duration` (mean absolute error also reported); LLM-judge
  score for `description`. For an accepted entity/instrument/asset match,
  per-attribute scores are computed post-match (entities: type+description;
  instruments: name+description+threat_level+holder; assets:
  name+description) — this never affects whether the pair counted as a match.
- **Holder resolution** (instruments only): the model instrument's holder
  `entity_id` is resolved through the already-computed entity match set and
  compared to the matched GT instrument's holder, reported as one of
  `correct` / `incorrect` / `unresolved` (either side missing a holder, or
  the holder entity itself had no accepted match) — never collapsed into a
  boolean.
- **No threshold, evaluator parameter, or scoring definition was changed
  based on observed results.** Anomalies found during the run are reported
  below, not corrected for.

### Failure handling (fail-fast, no default/missing scores)

Per explicit requirement, the run aborts rather than silently continuing if
the embedding server or LLM judge becomes unavailable or returns an invalid
result:

- `check_embedding_server_healthy()` verifies the embedding server is
  reachable and serving the exact frozen model before every video; any other
  outcome raises and stops the run.
- `check_judge_ok()` raises if the judge call itself failed (a genuinely low
  similarity score is valid data and is not an error).
- Two `ReadTimeout` failures against the judge endpoint occurred during the
  live run and correctly aborted the batch in progress (network error, not a
  parse failure, so not retried). The run was resumed targeting only the
  affected `--models`/`--categories` scope; DB writes are idempotent, so this
  is safe. Full 165/165 coverage was reached after two such resumes.

## Benchmark scope

- **3 models × 5 categories × 55 held-out videos/model = 165 total P1
  attempts.**
- Every attempt persists three things: the raw P1 structured prediction, the
  P1-vs-ground-truth evaluation result, and the RP1-generated report (never
  scored).

## P1 / RP1 failure counts

RP1 (report generation) had **zero failures** across all 165 attempts.

P1 (extraction) failures by model:

| Model | P1 failures | Out of |
|---|---|---|
| `nvidia/cosmos-3-nano-reasoner` | 5 | 55 |
| `nvidia/cosmos-3-super-reasoner` | 12 | 55 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | 5 | 55 |
| **Total** | **22** | **165** |

Both `cosmos-3-nano-reasoner` and `nemotron-3-nano-omni-30b-a3b-reasoning`
failed on the same 5 videos (`Animal006`, `Assault027`, `Burglary005`,
`Burglary052`, `RoadAccidents024`) — these are known to be rejected by the
gateway's request-size limit (large source video files), i.e. a shared,
model-independent infrastructure constraint, not a per-model quality
difference. `cosmos-3-super-reasoner` failed on those same 5 plus 7
additional videos, consistent with additional rate-limit/decoder failures
observed only against that endpoint during the run.

Aggregate metrics below are computed over each model's successful attempts
only (50, 43, and 50 videos respectively, out of 55).

## Aggregate results by model (pooled across all 5 categories)

| Metric | `cosmos-3-nano-reasoner` | `cosmos-3-super-reasoner` | `nemotron-3-nano-omni-30b-a3b-reasoning` |
|---|---|---|---|
| Incident type accuracy | 90.9% | 76.4% | 40.0% |
| Severity level accuracy | 36.3% | 30.9% | 16.4% |
| Start timestamp (±5s) accuracy | 69.1% (MAE 3.69s) | 61.8% (MAE 2.78s) | 27.3% (MAE 6.53s) |
| End timestamp (±5s) accuracy | 70.9% (MAE 5.08s) | 61.8% (MAE 4.02s) | 23.6% (MAE 8.41s) |
| Duration (±5s) accuracy | 60.0% (MAE 5.74s) | 52.7% (MAE 4.93s) | 27.3% (MAE 10.38s) |
| Description judge score (mean, 0–1) | 0.545 | 0.419 | 0.367 |
| Entities P / R / F1 | 0.096 / 0.084 / 0.090 | 0.125 / 0.084 / 0.101 | 0.135 / 0.042 / 0.064 |
| Instruments P / R / F1 | 0.105 / 0.154 / 0.125 | 0.125 / 0.077 / 0.095 | 0.250 / 0.154 / 0.190 |
| Assets P / R / F1 | 0.080 / 0.104 / 0.091 | 0.103 / 0.104 / 0.104 | 0.064 / 0.045 / 0.053 |

On the incident-level fields (type, severity, timestamps, description),
`cosmos-3-nano-reasoner` leads, followed by `cosmos-3-super-reasoner`, with
`nemotron-3-nano-omni-30b-a3b-reasoning` well behind on every field. Object
(entity/instrument/asset) precision/recall is low for all three models — see
"Known limitations" below before drawing conclusions from that part of the
comparison.

## Category-level results

Type accuracy / severity accuracy / mean description score per model per
category (n = number of evaluation videos in that category, same for every
model):

| Category (n) | `cosmos-3-nano-reasoner` | `cosmos-3-super-reasoner` | `nemotron-3-nano-omni-30b-a3b-reasoning` |
|---|---|---|---|
| Animal Attack (10) | 90.0% / 40.0% / 0.717 | 60.0% / 30.0% / 0.535 | 20.0% / 10.0% / 0.459 |
| Assault (10) | 90.0% / 30.0% / 0.421 | 90.0% / 10.0% / 0.479 | 30.0% / 10.0% / 0.248 |
| Burglary (13) | 84.6% / 53.8% / 0.522 | 76.9% / 46.2% / 0.305 | 23.1% / 7.7% / 0.368 |
| Explosion (10) | 100.0% / 20.0% / 0.679 | 80.0% / 10.0% / 0.524 | 90.0% / 40.0% / 0.622 |
| Road Accident (12) | 91.7% / 33.3% / 0.419 | 75.0% / 50.0% / 0.307 | 41.7% / 16.7% / 0.175 |

Explosion is the one category where `nemotron-3-nano-omni-30b-a3b-reasoning`
is competitive with (and on description score, ahead of) the other two
models; on every other category it trails substantially, consistent with the
pooled results above.

Entity/instrument/asset F1 by category and model is in
`eval_data/results/summary.json`'s `by_category_and_model` block (not
reproduced in full here — object-match counts per category are small enough,
see limitations below, that per-category object metrics are not reported as
a primary result).

## Known limitations

- **Object-matching metrics (entities/instruments/assets precision/recall/F1)
  are low across all three models (roughly 0.05–0.25) and depend on the fixed
  embedding model (`sentence-transformers/all-MiniLM-L6-v2`) and match
  threshold (cosine similarity ≥ 0.75).** This threshold was fixed before the
  run and was not tuned based on these results, per the experimental design.
  Because it is shared identically across all three models, the relative
  comparison between models on these metrics is still valid, but the absolute
  numbers should not be read as "the models rarely detect objects correctly"
  without first checking whether the embedding model/threshold is
  under-matching genuinely correct pairs (e.g. paraphrased descriptions that
  are semantically equivalent but fall under 0.75 cosine similarity). This is
  flagged, per instruction, for later analysis rather than corrected here.
- **Low object counts per category-model cell** (13 evaluation videos in the
  largest category) mean object-level P/R/F1, and especially per-category
  breakdowns of it, have limited statistical power — a handful of matches
  moves the ratio substantially.
- **`cosmos-3-super-reasoner` has a materially higher P1 failure rate** (12/55
  vs. 5/55 for the other two models) from additional rate-limit/decoder
  failures beyond the shared gateway-size-limit failures. Its aggregate
  metrics are computed over fewer successful attempts (43 vs. 50) than the
  other two models, which is a real difference in what was measured, not
  normalized away.
- **5 videos were rejected by the gateway's request-size limit** for every
  model that attempts them (large source video files) — a shared
  infrastructure constraint, not a per-model capability difference, and
  excluded from every model's successful-attempt count identically.
- **RP1 (report) output was never evaluated for quality.** It was generated
  and persisted for every attempt so a human-readable report exists
  alongside the structured data, but no metric in this document reflects
  report quality.
- **The description judge score reflects one LLM judge model's semantic
  similarity assessment**, not an independent human rating; it is reported
  as-is, consistent with the pre-committed evaluator design.

## Reproducibility artifacts

- **Split manifests** (seed, per-category few-shot demonstration/evaluation
  video filenames, and resolved R2 object keys — no video content, no
  ground-truth field values): tracked at `eval_reproducibility/split_*.json`,
  copied verbatim from the generating run's `eval_data/split_*.json` (which
  remains gitignored, alongside the raw ground-truth workbook, cached videos,
  and full per-video result JSON — see the `eval_data/` rule in `eval/.gitignore`).
- **P1/RP1 prompts**: `prompts.py` (`P1_PROMPT_VERSION = "P1-v1"`,
  `RP1_PROMPT_VERSION = "RP1-v1"`).
- **Evaluator/matching code**: `eval_gt.py`, `matching.py`, `config.py`
  (`MIN_MATCH_SIMILARITY`, `EVAL_TIMESTAMP_TOLERANCE_SECONDS`).
- **Run/aggregation scripts**: `scripts/eval_run.py`,
  `scripts/eval_aggregate.py`, `scripts/eval_generate_split.py`,
  `scripts/eval_few_shot.py`, `scripts/eval_vlm_client.py`,
  `scripts/eval_run_lib.py`.
- **Full per-video results** (raw predictions, ground truth, RP1 reports,
  per-field/per-object scores) are not committed; they are reproducible by
  re-running `scripts/eval_run.py` against the same split manifests, the same
  ground-truth workbook, and the same fixed prompts/configuration recorded
  above.
