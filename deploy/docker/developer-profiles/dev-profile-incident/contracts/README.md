# Incident contract (`incident-contract-v4`)

This directory is the single source of truth for incident extraction: one prompt and one output schema, shared by `eval/`, `incident-console-v2/` and `vss-agent`. This directory is the only place to edit shared contract files; run `python sync.py` (or `python sync.py --check`) to regenerate the agent's vendored copy in `services/agent/src/vss_agents/incident_contract/`. Decisions: [`../.docs/decisions.md`](../.docs/decisions.md).

**Status:** all consumers are on the contract. `eval/` runs P1 and RP1 on the contract (`eval/contract.py`, `eval/scripts/eval_run.py`). `incident-console-v2/` (gateway and agent mode) uses it too (`lib/contract/`, `lib/analysis/build-request.ts`, `lib/analysis/run-contract-analysis.ts`), with the ID-only `id-normalization-v1` recovery on top of strict validation (application only; eval scores first responses). `vss-agent` vendors the contract under `services/agent/src/vss_agents/incident_contract/` and executes P1/RP1 directly.

| File | Purpose |
|---|---|
| [`incident_report.schema.json`](incident_report.schema.json) | JSON Schema (draft 2020-12) for the P1 output. It is sent to the model as `response_format: json_schema` (strict) and validates every response. |
| [`incident_extraction_prompt.txt`](incident_extraction_prompt.txt) | P1 prompt. It defines field **meaning** only; the schema defines the shape, so there is no JSON template, and there is no few-shot block. |
| [`report_generation_prompt.txt`](report_generation_prompt.txt) | RP1 prompt (derived P1 JSON → prose report). Its one placeholder is `{structured_incident_json}`. |
| [`VERSION`](VERSION) | Contract version, stored as `prompt_version` on model runs |
| [`inference.json`](inference.json) | Shared P1 and RP1 inference settings and the allowlist of VLMs the console may call (with per-model timeouts). The agent reads its `p1`/`rp1` blocks directly; eval reads its default client timeout from this file and `eval/tests/test_contract_fixtures.py` asserts its model list and P1/RP1 settings match. |
| [`fixtures/`](fixtures/) | Valid and invalid example reports, plus the expected `response_format`. Both the Python validator (`eval/tests/test_contract_fixtures.py`) and the console's TypeScript validator (`incident-console-v2/tests/contract-validate.test.mjs`) must agree on every fixture. `fixtures/policy/` holds recorded model responses and boundary cases, each with its video length and its expected verdict under validation policy `core-scored-v1` (below); `incident-console-v2/tests/contract-policy.test.mjs` checks the same set. |
| [`search-contract-v1/`](search-contract-v1/) | MVP2 search contract defining request/response JSON schemas and fixtures for `POST /api/v1/incidents/search` (jump-to-clip timestamps, labels, crop image references, and always-on critic). |
| [`chat-contract-v1/`](chat-contract-v1/) | MVP2 chat contract defining request/response JSON schemas and fixtures for `POST /api/v1/incidents/chat` (multi-turn conversational Q&A and grounded evidence citations). |
| [`sync.py`](sync.py) | Synchronises shared contract files to the vendored agent directory (`services/agent/src/vss_agents/incident_contract/`). Supports `--check` for drift detection. |

## Rules

- **Strict-mode compatible schema.** Every object has `additionalProperties: false`, and all of its properties are listed in `required`. An optional value is written as a nullable type, never by leaving it out of `required`.
- **Strict parsing.** A response is valid only if all three hold:
  - `json.loads` / `JSON.parse` of the raw `content` succeeds, with no fence stripping or brace extraction;
  - it passes schema validation;
  - it passes the cross-field rules below.

  This is **full contract validity** (`full_contract_ok` in eval, `fullContractValid` in console records). What consumers persist and score is decided by the validation policy below; nothing is ever repaired except by the application's ID-only rule (`id-normalization-v1`, in the console and `vss-agent`).
- **Cross-field rules** (in `eval/contract.py` `cross_field_errors`, ported to `incident-console-v2/src/modules/contract/domain/validate.ts` `crossFieldErrors` and `services/agent/src/vss_agents/incident_contract/` `cross_field_violations`):
  - `end_timestamp >= start_timestamp`;
  - IDs run in sequence: `E1..En`, `I1..In`, `A1..An`;
  - every `instruments[].entity_id` is `null` or an existing entity;
  - timeline events fall within `[start_timestamp, end_timestamp]` and are in chronological order.
- **Derived fields are computed by code, never requested from the model.** `incident.duration` is not in the schema. Every consumer sets it to `end_timestamp - start_timestamp` after validation (`eval/contract.py`, `with_derived_fields`), and RP1 receives the derived JSON. A model that sends `duration` fails the schema.
- **Temporal and visual grounding (`incident-contract-v3`):** `entities`, `instruments`, and `assets` items require `timestamp_seconds` (integer >= 0) and `label` (short detector string) for temporal grounding and evidence crop localisation. Per the VLM Bounding Box Accuracy Pilot, spatial bounding boxes are never requested from or emitted by VLMs; they are optional, detector-produced outputs in search hits.
- **Entity seen span (`incident-contract-v4`):** every entity also requires `first_seen_seconds` and `last_seen_seconds` (integer >= 0, seconds from video start). The prompt asks for `first_seen_seconds <= timestamp_seconds <= last_seen_seconds`; the schema cannot express that and no cross-field rule enforces it. They are required in the schema because strict mode lists every property in `required`. Reports stored before v4 lack them, so readers fall back to `timestamp_seconds` and the console validates an older report against its own version's schema.
- **Validation policy `core-scored-v1`** (a layer on top of these rules; `eval/contract.py` `evaluate_policy`, console `lib/contract/validate.ts` `validateCore`, agent `vss_agents/incident_contract/` `core_violations`). Only the database-backed fields decide whether a response is persisted and how the model scores:
  - incident type, window, description, severity and confidence;
  - entities, instruments and assets.

  `title`, `severity_reason`, `location`, `timeline` and `uncertainties` are best-effort enrichment: never scored, and a cross-field failure confined to them (the `TIMELINE_*` rules) is recorded, not fatal, and never repaired, clipped or removed. This is **core validity** (`core_ok` / `coreValid`).
  - **Still fatal:** every schema violation (isolating a valid core from a schema-invalid document would need partial parsing, so it is out of scope) and every other cross-field rule.
  - **Contextual rule** (runtime input, not the schema): when the video's length is known (read from its MP4 header), every whole-second incident timestamp T must satisfy `0 <= T < duration + 1`. A moment in the last partial second may be written as the next whole second, nothing later (`WINDOW_BEYOND_VIDEO`, core). Timeline times are checked the same way (`TIMELINE_BEYOND_VIDEO`, enrichment). An unknown length is recorded as not checked, never as passed. The contextual rules never change full contract validity.
  - The policy id is recorded next to the contract version in console attempt records and eval results. The prompt and schema are unchanged by it; it was introduced without a `VERSION` bump because nothing sent to or returned by the model changed. Only the consequence of the existing rules and one contextual check did (decision 2026-09-27 in `../.docs/decisions.md`).
- **RP1 execution under `core-scored-v1`:** RP1 report generation runs on `core_ok` (rather than requiring `full_contract_ok`), receiving the derived JSON with its unchanged prediction (including lead-up or aftermath timeline events). `report_generation_prompt.txt` includes the explicit rule that timeline events outside the incident time are context. Since `report_generation_prompt.txt` changed, `VERSION` is bumped to `incident-contract-v3` per the profile contract versioning rule (decision 2026-10-16 in `../.docs/decisions.md`).
- **Changing anything here** means bumping `VERSION`, updating every consumer in the same PR, and updating [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md) once the contract is live. Taxonomy changes also need a database migration.

## Model evidence

The probe results are recorded in [`../.docs/analysis-schema.md` §7](../.docs/analysis-schema.md#7-model-inference-findings). They cover schema enforcement per model, URL fetching, the gateway's ~24-frame default, and Super ignoring `num_frames`. The probe script itself was removed after phase 0. The eval run is now the measure of each model on the contract.
