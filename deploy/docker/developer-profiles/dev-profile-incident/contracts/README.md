# Incident contract (`incident-contract-v2`)

This directory is the single source of truth for incident extraction: one prompt and one output schema, shared by `eval/`, `incident-console-v2/` and `vss-agent`. Background and phasing are in [`../.docs/prompt-contract-plan.md`](../.docs/prompt-contract-plan.md).

**Status:** every consumer reads this directory.

| Consumer | Reads | Validator |
|---|---|---|
| `eval/` | directly (`eval/contract.py`) | `jsonschema` + cross-field rules |
| `incident-console-v2/` | at runtime from `INCIDENT_CONTRACTS_DIR` (default `../contracts`) in `lib/analysis/contract.ts` | Ajv + cross-field rules |
| `vss-agent` | a **vendored copy** in `services/agent/src/vss_agents/incident_contract/`, because the agent is deployed from `services/agent` | strict Pydantic + cross-field rules |

| File | Purpose |
|---|---|
| [`incident_report.schema.json`](incident_report.schema.json) | JSON Schema (draft 2020-12) for the P1 output. It is sent to the model as `response_format: json_schema` (strict) and validates every response. |
| [`incident_extraction_prompt.md`](incident_extraction_prompt.md) | P1 prompt. It defines field **meaning** only; the schema defines the shape, so there is no JSON template, and there is no few-shot block. |
| [`report_generation_prompt.md`](report_generation_prompt.md) | RP1 prompt (derived P1 JSON → prose report). Its one placeholder is `{structured_incident_json}`. |
| [`p1_request.json`](p1_request.json) | Fixed P1 settings merged into every P1 request: `temperature`, `max_tokens` (16384, for reasoning models), `media_io_kwargs` (64 frames). |
| [`rp1_request.json`](rp1_request.json) | Fixed RP1 request: `model` plus its settings (thinking off). |
| [`VERSION`](VERSION) | Contract version, stored as `prompt_version` on model runs |

## Rules

- **Strict-mode compatible schema.** Every object has `additionalProperties: false`, and all of its properties are listed in `required`. An optional value is written as a nullable type, never by leaving it out of `required`.
- **Strict parsing.** A response is valid only if all three hold:
  - `json.loads` / `JSON.parse` of the raw `content` succeeds, with no fence stripping or brace extraction;
  - it passes schema validation;
  - it passes the cross-field rules below.

  Anything else is an error (HTTP 422 in services), never repaired.
- **Cross-field rules** (`cross_field_errors` in `eval/contract.py`, `incident-console-v2/lib/analysis/contract.ts` and `vss_agents/incident_contract/__init__.py`; keep the three identical):
  - `end_timestamp >= start_timestamp`;
  - IDs run in sequence: `E1..En`, `I1..In`, `A1..An`;
  - every `instruments[].entity_id` is `null` or an existing entity;
  - timeline events fall within `[start_timestamp, end_timestamp]` and are in chronological order.
- **Derived fields are computed by code, never requested from the model.** `incident.duration` is not in the schema. Every consumer sets it to `end_timestamp - start_timestamp` after validation (`with_derived_fields` / `withDerivedFields`), and RP1 receives the derived JSON. A model that sends `duration` fails the schema.
- **Changing anything here** means bumping `VERSION`, copying the directory into `services/agent/src/vss_agents/incident_contract/` (its parity test fails otherwise), updating every consumer in the same PR, and updating [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md). Taxonomy changes also need a database migration.

## Model evidence

The phase 0 probe results are recorded in [`../.docs/prompt-contract-plan.md` §5a](../.docs/prompt-contract-plan.md#5a-phase-0-results). They cover schema enforcement per model, URL fetching, the gateway's ~24-frame default, and Super ignoring `num_frames`. The probe script itself was removed after phase 0. The eval run is now the measure of each model on the contract.
