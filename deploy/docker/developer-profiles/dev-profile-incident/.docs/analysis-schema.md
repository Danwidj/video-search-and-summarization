# Incident Analysis Schema & Output Alignment

This document describes how incident analysis output is defined, validated, stored and shown.

> [!NOTE]
> Since `incident-contract-v3`, **eval, `incident-console-v2` (gateway and agent mode) and `vss-agent` share one contract**: the same prompt, schema and P1 settings in [`../contracts/`](../contracts/README.md). Background and decisions: [`prompt-contract-plan.md`](prompt-contract-plan.md).

---

## 1. Principle

1. **`contracts/` defines the complete model output.** `incident_report.schema.json` (JSON Schema draft 2020-12), `incident_extraction_prompt.md` and `VERSION` are the source of truth for what the VLM must return and what counts as a valid response. In `incident-contract-v3`, entities, instruments, and assets require `timestamp_seconds` (integer >= 0) and `label` (short detector string) for temporal grounding and evidence crop localization. Spatial bounding boxes are detector-produced and optional in search hits, not VLM outputs.
2. **`model_runs.notes` stores the complete validated report and its provenance, immutably.** Nothing ever edits it.
3. **Relational tables are a query-optimised projection** (`incidents`, `entities`, `instruments`, `assets`). A field gets a column when it must be queried, filtered, aggregated, joined, edited, matched or charted.
4. **What the report page shows follows reviewer usefulness**, drawing from both the projection and the notes. The console translates the rows of one run (projection, review state, official selection, decoded notes) into a `RunReportRecord` in `incident-console-v2/lib/adapters/supabase/mappers/report.ts`; `toReportView` in `lib/reports/view.ts` builds the report view from that record without reading any column.

## 2. The analysis request (identical to eval P1)

`incident-console-v2/lib/analysis/build-request.ts` builds exactly the request of `eval/scripts/eval_vlm_client.py:analyze_video_with_p1`:

- **Model:** one of the allowlisted models in [`contracts/inference.json`](../contracts/inference.json): `nvidia/cosmos-3-nano-reasoner`, `nvidia/cosmos-3-super-reasoner`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning`.
- **`messages`:** one user message:
  1. the signed R2 video URL;
  2. the canonical extraction prompt, verbatim;
  3. only when a reviewer gave one, an **additional instruction** as a separate, fenced, lower-priority text part. It never edits the canonical prompt and cannot change the enforced schema; max 1,000 characters, control characters stripped.
- **Settings:** `temperature 0`, `max_tokens 16384`, `media_io_kwargs.video.num_frames 64` (Cosmos Super ignores `num_frames`).
- **`response_format`:** the contract schema, strict (`$schema`/`$id` removed), equal to `eval/contract.py:response_format()`.

## 3. Validation, ID-only repair and outcomes

`lib/contract/validate.ts` is a strict port of `eval/contract.py`:
- `JSON.parse` of the raw content, with no fence stripping, brace extraction, aliasing or defaults;
- Ajv validation against the shared schema file;
- the cross-field rules;
- derived `incident.duration = end_timestamp - start_timestamp`.

Every violation carries a machine-readable code: `EMPTY_CONTENT`, `INVALID_JSON`, `SCHEMA_VIOLATION`, `WINDOW_END_BEFORE_START`, `ID_NOT_SEQUENTIAL_{ENTITY,INSTRUMENT,ASSET}`, `INSTRUMENT_HOLDER_UNKNOWN`, `TIMELINE_{START,END}_OUTSIDE_WINDOW`, `TIMELINE_NOT_CHRONOLOGICAL`, and the contextual `WINDOW_BEYOND_VIDEO` / `TIMELINE_BEYOND_VIDEO`. Shared fixtures in `contracts/fixtures/` (including `fixtures/policy/`) are checked by both the Python and the TypeScript validator.

**Validation policy `core-scored-v1`** (`validateCore`; same as eval's `evaluate_policy`, see [`../contracts/README.md`](../contracts/README.md)):
- **Decides the outcome:** the database-backed (Class A) fields.
- **Scope of each violation:**
  - The `TIMELINE_*` codes are *enrichment*: recorded with `scope: "enrichment"`, never fatal and never repaired.
  - Every other code is *core*.
  - Schema violations stay fatal.
- **Video length:** the analysis reads the video's length from its MP4 header in R2 (`lib/video/mp4-duration.ts`, ranged reads) and records it as `request.videoDurationSeconds`.
  - When known, a whole-second window time T must satisfy `0 <= T < length + 1` (`WINDOW_BEYOND_VIDEO`, core).
  - When unknown (`null`), the rule is not applied and `videoBoundsChecked` is `false`.
- **Recorded on each attempt:** `validation: { firstPass (all violations, each with scope), policy, fullContractValid, coreValid, videoBoundsChecked }`.
  - `fullContractValid` is incident-contract validity exactly as before.
  - `coreValid` is the original response's validity under the policy, before any ID repair.

**`id-normalization-v1`** (`lib/contract/repair.ts`) is the only repair the application applies:
- **When it runs:** only when *every* core first-pass violation is `ID_NOT_SEQUENTIAL_*`, or an `INSTRUMENT_HOLDER_UNKNOWN` that renumbering resolves, and the response passed the schema. Enrichment (timeline) violations neither block nor trigger it and are left as they are.
- **What it may change:** identifiers, `instruments[].entity_id` references and list order. Nothing else.
  - Well-formed IDs keep their number, and lists are reordered.
  - Malformed or out-of-range IDs get the free numbers.
- **When it refuses:**
  - a renamed ID, or its new value, appears in any free text (free text is never edited);
  - duplicate IDs;
  - an unresolvable holder.
- **Checks:** an invariance check proves only IDs and order changed. Core validation then runs again.
- **Eval:** eval never uses this and scores the original first response only.

Every attempt that reaches the model has one outcome:

| Outcome | Meaning | Rows written |
|---|---|---|
| `valid_first_pass` | the first response's database-backed fields were valid (enrichment issues, if any, are recorded) | report rows + notes |
| `valid_after_structural_repair` | valid after `id-normalization-v1`; UI badge "Contract repair applied (IDs only)" | report rows + notes |
| `contract_failed` | invalid; repair ineligible or re-validation failed | `model_runs` notes only |
| `request_failed` | no usable answer: gateway error or timeout, non-JSON or missing completion, empty content, or `finish_reason` other than `stop` (e.g. `FINISH_LENGTH`) | `model_runs` notes only |

Failed attempts never create incident, report, review or evidence rows, and never appear as reports.

**Timeline presentation:** when the model's timeline is inconsistent with its own incident window, the report page says so ("Model-generated timeline, not consistent with the detected incident window"). Events outside the window are tagged as model context and stay seekable. Seeking is blocked only for a time outside the video, judged by the recorded length and by the player's own length. The run history notes the issue, and the run-details panel lists enrichment issues, the policy and full-contract validity.

## 4. Storage

### Immutable notes (`model_runs.notes`)

```json
{"incidentConsoleV2": {
  "recordType": "analysis_attempt",
  "status": "valid_first_pass | valid_after_structural_repair | contract_failed | request_failed",
  "stage": null,
  "failure": null,
  "contractVersion": "incident-contract-v3",
  "videoId": "…", "r2Key": "…", "modelRunId": "…", "attemptedAt": "…Z",
  "request": { "model": "…", "inferenceConfig": {}, "additionalInstruction": null, "promptSha256": "…", "schemaSha256": "…" },
  "response": { "content": "<original raw response, unaltered>", "reasoningContent": "…", "finishReason": "stop", "usage": {} },
  "validation": { "firstPass": [ { "code": "…", "path": "…", "message": "…" } ] },
  "repair": null,
  "report": {},
  "reportId": "…", "generatedAt": "…"
}}
```

Field notes:
- `stage`: `null` for successful attempts; otherwise `gateway`, `upstream_response`, `contract_validation` or `structural_repair`.
- `failure`: `null` for successful attempts; otherwise `{ "code": "…", "message": "…" }`.
- `repair`: `null`, or `{ eligible: false, reason, blockingCodes }`, or `{ eligible: true, ruleSet, operations, revalidation }`.
- `report`: the final validated contract report plus derived duration. Valid outcomes only.
- `reportId` and `generatedAt`: valid outcomes only.
- `response`: holds only the fields the gateway actually returned.

Stage-1 records (before 2026-09-27 12:00) lack `status`; they are shown as `valid_first_pass` (inferred). Pre-contract console records are "earlier analyses", never failures.

### Three classes of report fields

| Class | Fields | Source | Editable |
|---|---|---|---|
| **A: structured** | type, start/end (integer seconds as text), duration (derived), description, severity level, confidence (model-sourced), entities (`E#`, human/animal/unknown), instruments (`I#`, holder, threat 1-5), assets (`A#`) | `incidents`, `entities`, `instruments`, `assets` | Yes, except duration (recomputed) and confidence |
| **B: model output** | title, severity rationale, location, timeline, uncertainties | the report in notes | No (read-only) |
| **C: provenance** | model, contract version, run id, instruction, settings, fingerprints, raw response, reasoning, finish reason, usage, repair record | notes + `model_runs` | No |

**Reviewer edits** (`apply_structured_report_edit`) change Class A only:
- the edit is validated against the contract's own sub-schemas and the ID/holder/window rules, and applied in one transaction;
- it sets `review_status.edited_by/edited_at`;
- it never touches notes.

The report page:
- shows "Model severity rationale";
- when a reviewer changed the severity, adds "Model assessed N/5; reviewer set M/5";
- marks every other reviewer-changed structured field ("Reviewer-edited after generation").

## 5. Legacy data

Older rows are shown in contract form for display and querying. Migration `20261016010000_legacy_taxonomy_and_orphan_cleanup.sql` rewrites the stored `incidents.type` and `entities.type` values once, but folding stays until the migration is applied (agent mode now writes contract values, as phase 3 is complete). Notes and timestamps are never rewritten:
- `fighting` → `assault`, `animal` → `animal attack`;
- entity `person` → `human`;
- `M:SS` / `H:MM:SS` → seconds.

Their notes are parsed best-effort for the read-only Class B fields. Saving an edit on a legacy run writes contract-form values for that run; its historical notes are untouched.

## 6. Agent mode

`ANALYSIS_MODE=agent` posts to `vss-agent`'s `/api/v1/incidents/{id}/analyze` with `{ video_url, model_run_id? }`.
- `vss-agent` uses its vendored `incident-contract-v3` (`vss_agents/incident_contract/`) to run P1 (direct VLM call with JSON Schema response format) and RP1 (prose report generation). The request's `skip_rp1` flag runs P1 only; the console always sets it, because gateway mode runs P1 only too.
- The agent validates P1 with strict Pydantic models under the same `core-scored-v1` policy and `id-normalization-v1` repair as the console (timeline-only violations are not fatal), derives `incident.duration` and, unless `skip_rp1`, runs RP1 on the result. Only a schema or unrepairable core violation is a 422, whose `detail` carries `raw_output`, `finish_reason`, `model` and `contract_version`. The video-length rules are left to the console, which reads the video length.
- With `model_run_id` (console agent mode) the agent persists nothing. Without it (a standalone call) it persists best-effort rows in PostgREST (`model_runs`, `incidents`, `entities`, `instruments`, `assets`) under its configured run id. It never writes `videos`.
- In `incident-console-v2`, `runContractAnalysis` routes the agent's raw P1 output (from a 200 or a 422) through the identical validation policy (`core-scored-v1`) and ID repair (`id-normalization-v1`) as gateway mode, records the attempt with the agent's model and finish reason in `model_runs.notes`, and writes every row itself through `persistContractRun`. Its timeout is the model's, as in gateway mode, since only P1 runs. A non-empty `additionalInstruction` is a 400 in agent mode, because the agent does not take one. If the agent's `contract_version` (from a 200 or a 422) is missing or differs from the console's, the attempt is a `request_failed` with code `CONTRACT_VERSION_MISMATCH` (HTTP 502, agent output kept in the notes, no report rows).
- Legacy agent-mode contract files (`lib/analysis/schema.ts`, `lib/analysis/incident-report-contract.json`, and `tests/contract-parity.test.mjs`) have been retired.

