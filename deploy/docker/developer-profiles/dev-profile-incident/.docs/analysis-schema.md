# Incident Analysis Schema & Output Alignment

How incident analysis output is defined, validated, stored and shown. Eval, `incident-console-v2` (gateway and agent mode) and `vss-agent` share one contract: the same prompt, schema and P1 settings in [`../contracts/`](../contracts/README.md).

## 1. Principle

1. **`contracts/` defines the complete model output.** `incident_report.schema.json` (JSON Schema draft 2020-12), `incident_extraction_prompt.txt` and `VERSION` are the source of truth for what the VLM must return and what counts as a valid response. The schema is strict-mode compatible: every object has `additionalProperties: false` and lists all its properties in `required`, so an optional value is a nullable type. `incident.duration` is not in the schema; every consumer derives it after validation. Bounding boxes are detector-produced, not VLM outputs.
2. **`model_runs.notes` stores the complete validated report and its provenance, immutably.** Nothing ever edits it.
3. **A report is a JSONB snapshot with queryable facets.** `report_revisions.payload` holds the whole contract report and `report_revisions.evidence` the evidence list; only the fields statistics filter on are copied into columns. `evidence_crops` is the search projection of each video's searchable revision ([`data.md`](data.md#evidence_crops)).

## 2. The analysis request (identical to eval P1)

`incident-console-v2/src/modules/analysis/application/build-request.ts` builds exactly the request of `eval/scripts/eval_vlm_client.py:analyze_video_with_p1`:

- **Model:** one of the allowlisted models in [`contracts/inference.json`](../contracts/inference.json); `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` is the default when `VLM_MODEL` is unset.
- **`messages`:** one user message: the signed R2 video URL; the canonical extraction prompt, verbatim; and, only when a reviewer gave one, an **additional instruction** as a separate, fenced, lower-priority text part (max 1,000 characters, control characters stripped). It never edits the canonical prompt and cannot change the enforced schema.
- **Settings:** `temperature 0`, `max_tokens 16384`, `media_io_kwargs.video.num_frames 64` (Cosmos Super ignores `num_frames`).
- **`response_format`:** the contract schema, strict (`$schema`/`$id` removed), equal to `eval/contract.py:response_format()`.

The exact bodies are request goldens in [`contracts/golden/`](../contracts/golden/README.md), which the console, eval and the agent each test against. Every other prompt is registered in [`contracts/prompts/`](../contracts/prompts/README.md).

## 3. Validation, ID-only repair and outcomes

`src/modules/contract/domain/validate.ts` is a strict port of `eval/contract.py`: `JSON.parse` of the raw content (no fence stripping, brace extraction, aliasing or defaults), Ajv validation against the shared schema file, the cross-field rules, and the derived `incident.duration = end_timestamp - start_timestamp`.

Every violation carries a machine-readable code: `EMPTY_CONTENT`, `INVALID_JSON`, `SCHEMA_VIOLATION`, `WINDOW_END_BEFORE_START`, `ID_NOT_SEQUENTIAL_{ENTITY,INSTRUMENT,ASSET}`, `INSTRUMENT_HOLDER_UNKNOWN`, `TIMELINE_{START,END}_OUTSIDE_WINDOW`, `TIMELINE_NOT_CHRONOLOGICAL`, and the contextual `WINDOW_BEYOND_VIDEO` / `TIMELINE_BEYOND_VIDEO`.

**Validation policy `core-scored-v1`** (`validateCore`; eval's `evaluate_policy`; the agent's `core_violations`):

- The `TIMELINE_*` codes are *enrichment*: recorded with `scope: "enrichment"`, never fatal and never repaired. Every other code is *core*. Schema violations stay fatal.
- **Video length:** when the video's length is known (read from its MP4 header), a whole-second window time T must satisfy `0 <= T < length + 1` (`WINDOW_BEYOND_VIDEO`, core). When unknown, the rule is not applied and `videoBoundsChecked` is `false`.
- **Recorded on each attempt:** `validation: { firstPass (all violations, each with scope), policy, fullContractValid, coreValid, videoBoundsChecked }`.

**`id-normalization-v1`** (`src/modules/contract/domain/repair.ts`, mirrored in `vss_agents/incident_contract`) is the only repair the application applies:

- **When it runs:** only when *every* core first-pass violation is `ID_NOT_SEQUENTIAL_*`, or an `INSTRUMENT_HOLDER_UNKNOWN` that renumbering resolves, and the response passed the schema.
- **What it may change:** identifiers, `instruments[].entity_id` references and list order. Nothing else; free text is never edited.
- **Eval** never uses this and scores the original first response only.

Every attempt that reaches the model has one outcome:

| Outcome | Meaning | Rows written |
|---|---|---|
| `valid_first_pass` | the first response's database-backed fields were valid (enrichment issues, if any, are recorded) | AI revision + notes |
| `valid_after_structural_repair` | valid after `id-normalization-v1`; UI badge "Contract repair applied (IDs only)" | AI revision + notes |
| `contract_failed` | invalid; repair ineligible or re-validation failed | `model_runs` notes only |
| `request_failed` | no usable answer: gateway error or timeout, non-JSON or missing completion, empty content, or `finish_reason` other than `stop` (e.g. `FINISH_LENGTH`) | `model_runs` notes only |

Failed attempts never create a revision or evidence rows, and never appear as reports.

**Unscored output is not displayed:** the console shows no timeline and no model-reported uncertainties. The issues stay recorded in `model_runs.notes` under `validation.firstPass`.

## 4. Storage

### Immutable notes (`model_runs.notes`)

```json
{"incidentConsoleV2": {
  "recordType": "analysis_attempt",
  "status": "valid_first_pass | valid_after_structural_repair | contract_failed | request_failed",
  "stage": null,
  "failure": null,
  "contractVersion": "incident-contract-v4",
  "videoId": "…", "r2Key": "…", "modelRunId": "…", "attemptedAt": "…Z",
  "request": { "model": "…", "inferenceConfig": {}, "additionalInstruction": null, "promptSha256": "…", "schemaSha256": "…", "videoDurationSeconds": 0 },
  "response": { "content": "<original raw response, unaltered>", "reasoningContent": "…", "finishReason": "stop", "usage": {}, "httpStatus": 200, "errorBody": null, "tracking": {}, "object_tracking": {} },
  "validation": { "firstPass": [ { "code": "…", "path": "…", "message": "…" } ] },
  "repair": null,
  "report": {},
  "reportId": "…", "generatedAt": "…"
}}
```

- `stage`: `null` for successful attempts; otherwise `gateway`, `upstream_response`, `contract_validation` or `structural_repair`.
- `failure`: `null` for successful attempts; otherwise `{ "code": "…", "message": "…" }`.
- `repair`: `null`, or `{ eligible: false, reason, blockingCodes }`, or `{ eligible: true, ruleSet, operations, revalidation }`.
- `report`, `reportId` and `generatedAt`: valid outcomes only.
- `request.videoDurationSeconds`, `response.httpStatus`, `response.errorBody`, `response.tracking`, `response.object_tracking` and `response.provenance` are agent mode only, copied as returned.

### Three classes of report fields

| Class | Fields | Source | Editable |
|---|---|---|---|
| **A: structured** | type, title, start/end (integer seconds as text), duration (derived), description, severity level, severity rationale (stored as `incident.severity_reason`), confidence (model-sourced), entities (`E#`, human/animal/unknown), instruments (`I#`, holder, threat 1-5), assets (`A#`), and each item's description, detail and image | `report_revisions.payload` and `.evidence` | Yes, into a new `human` revision only, except duration (recomputed) and confidence |
| **B: model output** | location (shown); the model's original title (shown beside a reviewer's); timeline and uncertainties (stored in the report, not shown by the console) | the report in notes | No (read-only) |
| **C: provenance** | model, contract version, run id, instruction, settings, fingerprints, raw response, reasoning, finish reason, usage, repair record | notes + `model_runs` | No |

### Report revisions (AI and human)

A report is a list of immutable revisions in `report_revisions`; the columns, the append-only trigger and the official and searchable revisions are in [`data.md`](data.md#the-report-model).

| Event | Revision written |
|---|---|
| Successful analysis | `kind='ai'`, `parent_id` NULL, `model_run_id` set |
| First Save as new version | `kind='human'`, `parent_id` = the revision opened, complete payload and evidence, `created_by` |
| Later saves | another `human` revision on the current one |
| Re-generation | a new `ai` revision with `parent_id` NULL; it copies no earlier edits |
| Mark official | none; `videos.official_revision_id` changes and `evidence_crops` is rebuilt |
| Delete video | cascade removes every revision |

- **The official revision** is the version statistics count.
- **The report page** opens `?revision=<id>`, else the official revision, else the newest one.
- **Evidence images** are never overwritten; a reviewer image is uploaded on Save to a new key ([R2 layout](data.md#2-cloudflare-r2-storage-architecture)). An item the detector could not find has `located: false`, a frame and no box; an item without a frame records an `image_gap` reason.
- **There is no verification status and no draft.** Unsaved edits live only in the form.

## 5. Legacy data

Older rows are shown in contract form for display and querying: `fighting` → `assault`, `animal` → `animal attack`, entity `person` → `human`, `M:SS` / `H:MM:SS` → seconds. Their `model_runs.notes` are never rewritten.

## 6. Agent mode

`ANALYSIS_MODE=agent` posts to `vss-agent`'s `/api/v1/incidents/{id}/analyze` ([request and response](vm-api-contracts.md#post-apiv1incidentsincident_idanalyze)).

- **Contract:** `vss-agent` runs P1 with its vendored `incident-contract-v4` (`vss_agents/incident_contract/`) and the `p1` settings of `contracts/inference.json`. The console always sets `skip_rp1`, because gateway mode runs P1 only too.
- **Validation:** the agent validates P1 under the same `core-scored-v1` policy and `id-normalization-v1` repair as the console. Only a schema or unrepairable core violation is a 422, whose `detail` carries `raw_output`, `finish_reason`, `model` and `contract_version`.
- **Persistence:** after a valid report the agent (given `video_key`, the video's R2 key) appends the `report_revisions` row (`kind='ai'`), locates each evidence item, and uploads the whole frame and the crop to R2. It never writes `videos`.
- **Console side:** `runContractAnalysis` routes the agent's raw P1 output (from a 200 or a 422) through the identical validation policy and ID repair as gateway mode and writes the `model_runs` notes itself; it only verifies the AI revision when the agent's response carries `revision_id`, and inserts it otherwise. A missing or different `contract_version` is a `request_failed` with code `CONTRACT_VERSION_MISMATCH`.

## 7. Model inference findings

Measured when the contract was introduced; they explain the fixed P1 settings in `contracts/inference.json`.

- **Frame sampling:** the default is about 24 frames per video whatever its length. `num_frames` takes effect on Nano and Nemotron; **Super ignores it**.
- **Token budget:** Nemotron needs about 16k tokens to reason and then emit JSON (4096 ended with `finish_reason=length`), hence `max_tokens 16384` and `num_frames 64` for every model.
- **Timeline rule:** Cosmos models often include lead-up or aftermath events outside their own incident window, which is why `core-scored-v1` records `TIMELINE_*` failures without rejecting the report.
- **Correctness is separate from validity:** a strict pass says nothing about accuracy. Eval is the measure of each model.
