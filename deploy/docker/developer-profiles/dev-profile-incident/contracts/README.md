# Incident contract (`incident-contract-v4`)

The single source of truth for incident extraction: one prompt, one output schema and the shared inference settings, used by `eval/`, `incident-console-v2/` and `vss-agent`.

| File | What it is |
|---|---|
| [`incident_report.schema.json`](incident_report.schema.json) | The P1 output schema, sent to the model as a strict `response_format` |
| [`incident_extraction_prompt.txt`](incident_extraction_prompt.txt) | The P1 prompt (field meaning only) |
| [`report_generation_prompt.txt`](report_generation_prompt.txt) | The RP1 prompt (P1 JSON to prose) |
| [`VERSION`](VERSION) | The contract version, stored as `prompt_version` on model runs |
| [`inference.json`](inference.json) | P1 and RP1 settings and the model allowlist |
| [`fixtures/`](fixtures/) | Valid, invalid and policy cases both validators must agree on |
| [`search-contract-v1/`](search-contract-v1/README.md), [`chat-contract-v1/`](chat-contract-v1/README.md) | The MVP2 search and chat HTTP contracts |

## Changing it

1. Edit the files here only, then run `python sync.py` to copy them into the agent (`python sync.py --check` reports drift).
2. Bump `VERSION` and update every consumer in the same PR; a taxonomy change also needs a migration.

How the contract is validated, repaired and stored: [`../.docs/analysis-schema.md`](../.docs/analysis-schema.md).
