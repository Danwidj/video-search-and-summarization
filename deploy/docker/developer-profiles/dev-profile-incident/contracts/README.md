# Incident contract (`incident-contract-v2`)

This directory is the single source of truth for incident extraction: one prompt and one output schema, shared by `eval/`, `incident-console-v2/` and `vss-agent`. Background and phasing are in [`../.docs/prompt-contract-plan.md`](../.docs/prompt-contract-plan.md).

**Status:** phase 1 done; phase 2 (console) in progress. `eval/` runs P1 and RP1 on the contract (`eval/contract.py`, `eval/scripts/eval_run.py`). `incident-console-v2/` gateway-mode analysis now uses it too (`lib/contract/`, `lib/analysis/build-request.ts`), but its report view is still being migrated. The agent keeps its own contract until phase 3.

| File | Purpose |
|---|---|
| [`incident_report.schema.json`](incident_report.schema.json) | JSON Schema (draft 2020-12) for the P1 output. It is sent to the model as `response_format: json_schema` (strict) and validates every response. |
| [`incident_extraction_prompt.md`](incident_extraction_prompt.md) | P1 prompt. It defines field **meaning** only; the schema defines the shape, so there is no JSON template, and there is no few-shot block. |
| [`report_generation_prompt.md`](report_generation_prompt.md) | RP1 prompt (derived P1 JSON → prose report). Its one placeholder is `{structured_incident_json}`. |
| [`VERSION`](VERSION) | Contract version, stored as `prompt_version` on model runs |
| [`inference.json`](inference.json) | Shared P1 inference settings and the allowlist of VLMs the console may call (with per-model timeouts). eval keeps its own constants; `eval/tests/test_contract_fixtures.py` asserts they match this file. |
| [`fixtures/`](fixtures/) | Valid and invalid example reports, plus the expected `response_format`. Both the Python validator (`eval/tests/test_contract_fixtures.py`) and the console's TypeScript validator (`incident-console-v2/tests/contract-validate.test.mjs`) must agree on every fixture. |

## Rules

- **Strict-mode compatible schema.** Every object has `additionalProperties: false`, and all of its properties are listed in `required`. An optional value is written as a nullable type, never by leaving it out of `required`.
- **Strict parsing.** A response is valid only if all three hold:
  - `json.loads` / `JSON.parse` of the raw `content` succeeds, with no fence stripping or brace extraction;
  - it passes schema validation;
  - it passes the cross-field rules below.

  Anything else is an error (HTTP 422 in services), never repaired.
- **Cross-field rules** (in `eval/contract.py` `cross_field_errors`, ported to `incident-console-v2/lib/contract/validate.ts` `crossFieldErrors`):
  - `end_timestamp >= start_timestamp`;
  - IDs run in sequence: `E1..En`, `I1..In`, `A1..An`;
  - every `instruments[].entity_id` is `null` or an existing entity;
  - timeline events fall within `[start_timestamp, end_timestamp]` and are in chronological order.
- **Derived fields are computed by code, never requested from the model.** `incident.duration` is not in the schema. Every consumer sets it to `end_timestamp - start_timestamp` after validation (`eval/contract.py`, `with_derived_fields`), and RP1 receives the derived JSON. A model that sends `duration` fails the schema.
- **Changing anything here** means bumping `VERSION`, updating every consumer in the same PR, and updating [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md) once the contract is live. Taxonomy changes also need a database migration.

## Model evidence

The phase 0 probe results are recorded in [`../.docs/prompt-contract-plan.md` §5a](../.docs/prompt-contract-plan.md#5a-phase-0-results). They cover schema enforcement per model, URL fetching, the gateway's ~24-frame default, and Super ignoring `num_frames`. The probe script itself was removed after phase 0. The eval run is now the measure of each model on the contract.
