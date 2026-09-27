# Incident Analysis Schema & Output Alignment

This document describes the incident report every analysis path produces, and how it is validated, stored and shown.

> [!NOTE]
> Since `incident-contract-v2`, **eval, `incident-console-v2` (gateway and agent mode) and `vss-agent` share one contract**: the same prompt, the same JSON Schema, the same request settings and the same strict parser. The source of truth is [`../contracts/`](../contracts/README.md). Background and decisions: [`prompt-contract-plan.md`](prompt-contract-plan.md).

---

## 1. The contract

| File (`contracts/`) | Role |
|---|---|
| `incident_report.schema.json` | JSON Schema (draft 2020-12), strict-mode compatible. It is sent as `response_format: json_schema` (strict) and validates every response. |
| `incident_extraction_prompt.md` | P1 prompt: the meaning of every field. There is no JSON template and no few-shot block. |
| `report_generation_prompt.md` | RP1 prompt: derived P1 JSON → prose report. |
| `p1_request.json` | Fixed P1 settings: `temperature 0`, `max_tokens 16384`, `media_io_kwargs {"video": {"num_frames": 64}}`. |
| `rp1_request.json` | Fixed RP1 model and settings: `nvidia/nemotron-3-nano-30b-a3b`, `temperature 0`, `max_tokens 4096`, thinking off. |
| `VERSION` | `incident-contract-v2`, stored as `model_runs.prompt_version`. |

### Shape

```text
incident
  type               "road accident" | "burglary" | "explosion" | "assault" | "animal attack"
  title              string
  start_timestamp    integer seconds >= 0
  end_timestamp      integer seconds >= start_timestamp
  duration           integer seconds, DERIVED by code (end - start), never requested from the model
  description        string
  severity_level     integer 1-5
  severity_reason    string
  confidence_score   number 0-1 | null   (null unless the model/API gives a native score)
  location           string | null
entities[]           entity_id "E1".."En", type "human" | "animal" | "unknown", description
instruments[]        instrument_id "I1".."In", entity_id (an E id) | null, name, description, threat_level 1-5
assets[]             asset_id "A1".."An", name, description
timeline[]           start_seconds, end_seconds | null, description  (all within [start_timestamp, end_timestamp], chronological)
uncertainties[]      string
```

### Cross-field rules

These are checked after the schema:
- `end_timestamp >= start_timestamp`.
- IDs are sequential.
- Every instrument holder is `null` or an existing entity.
- The timeline falls within the incident window and is in chronological order. This is kept strict: lead-up events are a violation (decision D11).

## 2. One call pattern, one parser

| Step | Request | Result |
|---|---|---|
| **P1** | The video as a **signed R2 URL** first, then `incident_extraction_prompt.md`, with the schema as strict `response_format` and `p1_request.json` settings. | The raw `content` must be one JSON document that passes the schema and cross-field rules, and `duration` is then added. There is **no** fence stripping, brace extraction, alias mapping, coercion or repair retry. A violation is **HTTP 422** and nothing is persisted. |
| **RP1** | Text only: `report_generation_prompt.md` with the derived P1 JSON, using `rp1_request.json`. | Prose report text. If RP1 fails, the valid P1 report is kept and `reportTextError` / `report_text_error` records why. |

| Consumer | Validator | Where |
|---|---|---|
| eval | `jsonschema` + cross-field rules | `eval/contract.py` |
| incident-console-v2 | Ajv (draft 2020-12) + cross-field rules | `incident-console-v2/lib/analysis/contract.ts` (server only; types in `contract-types.ts`) |
| vss-agent | Strict Pydantic (`strict=True`, `extra="forbid"`) mirroring the schema + cross-field rules | `services/agent/src/vss_agents/incident_contract/` (a vendored copy of `contracts/`) |

**Drift protection:**
- `services/agent/tests/unit_test/incident_contract/` fails if the vendored files differ from `contracts/`, or if the Pydantic models stop mirroring the schema.
- `incident-console-v2/tests/contract.test.mjs` checks the TS types and constants against the schema file.
- `eval/tests/test_contract.py` checks the schema's strict-mode shape and the prompt's taxonomy.

### Per analysis mode (`incident-console-v2`)

- **Gateway mode (`ANALYSIS_MODE=gateway`):** the console runs P1 and RP1 through `vlm-gateway`, which forwards the body unchanged, then persists everything (§3).
- **Agent mode (`ANALYSIS_MODE=agent`):**
  - The console sends `POST /api/v1/incidents/{id}/analyze` with `{model_run_id, video_url}`, where `video_url` is the same signed R2 URL.
  - `vss-agent` runs the identical P1 and RP1 and persists the incident rows.
  - It returns `{report, report_text, report_text_error, model, contract_version, raw_output}`.
  - The console validates `report` against the contract again, and persists the notes, the `videos` row (the R2 key) and `reports`.
  - `reasoning` and `prompt_override` are no longer accepted, because they would break "one prompt everywhere".

## 3. Persistence

### `model_runs.notes`

```json
{"incidentConsoleV2": {
  "report": { "...metadata...", "incident": {"...": "..."}, "entities": [], "instruments": [], "assets": [], "timeline": [], "uncertainties": [] },
  "rawModelOutput": "<P1 message content>",
  "reportText": "<RP1 prose>",
  "editedReport": { "...contract shape, only after a human edit..." }
}}
```

- The original AI `report` is never overwritten.
- Reviewer edits (`PATCH /api/reports/{videoId}/edit`) are validated against the same contract, get their `duration` recomputed and are stored as `editedReport`. An edit that breaks the contract returns **400**.

### Relational rows

| Table | Written from |
|---|---|
| `incidents` | `type`, `start_timestamp` / `end_timestamp` as **bare seconds** (`"3"`), the derived `duration`, `description`, `severity_level`, `confidence_score` (nullable), via the `insert_incident` RPC. |
| `entities` | `entity_id` (`E1`...), `type` (`human`/`animal`/`unknown`), `description`. |
| `instruments` | `instrument_id` (`I1`...), `entity_id` (holder or null), `name`, `description`, `threat_level`. |
| `assets` | `asset_id` (`A1`...), `name`, `description`. |

- **Gateway mode:** the console writes all of these.
- **Agent mode:**
  - the agent writes `model_runs`, `incidents` and the evidence tables;
  - the console writes the notes, `videos` and `reports`;
  - the agent **never** writes `videos`, so the durable R2 key is no longer overwritten.

`title`, `severity_reason`, `location`, `timeline`, `uncertainties` and the RP1 text live only in `model_runs.notes` until Option B ([`restructure-plan.md`](restructure-plan.md)).

## 4. Reports from before the contract

- **Stored reports:** notes written before `incident-contract-v2` (flat snake_case or camelCase, `persons`, `M:SS` times, self-reported confidence) are converted **read-only** for display by `legacyToContract` in `incident-console-v2/lib/reports/storage.ts`. They are flagged `legacy`, map `fighting` to `assault` and `animal` to `animal attack` for display, and are never written back.
- **Runs without notes** (eval, seed or older agent rows): these are rebuilt from the relational rows.
- **Database rows:** live rows still hold the old taxonomy until the phase 4 migration.
