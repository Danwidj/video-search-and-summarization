<!--
agents:
  read-when: Changing a model prompt, the incident output schema, the inference settings, or a search or chat contract.
  owns: the list of contract files and the steps to change the incident contract.
  rules: Edit the files here only, then run python sync.py. Bump VERSION and update every consumer in the same PR.
  check: python sync.py --check
-->

# Incident contract

The single source of truth for incident extraction (`incident-contract-v4`): one prompt, one output schema and the shared inference settings, used by `eval/`, `incident-console-v2/` and `vss-agent`.

## What is inside

| File | What it is |
|---|---|
| [incident_report.schema.json](incident_report.schema.json) | The P1 output schema, sent to the model as a strict `response_format` |
| [incident_extraction_prompt.txt](incident_extraction_prompt.txt) | The P1 prompt (field meaning only) |
| [report_generation_prompt.txt](report_generation_prompt.txt) | The RP1 prompt (P1 JSON to prose) |
| [VERSION](VERSION) | The contract version, stored as `prompt_version` on model runs |
| [inference.json](inference.json) | P1 and RP1 settings and the model allowlist |
| [fixtures/](fixtures/) | Valid, invalid and policy cases both validators must agree on, plus `response_format.json` and `chart-severity-words.json` |
| [prompts/](prompts/README.md) | Every other model prompt: the caption pass, the P1 preambles, grounding, the zoomed second look, chat and the exported chart prompt |
| [golden/](golden/README.md) | The exact request bodies sent to models; the console, eval and the agent each test theirs against them |
| [experiments/](experiments/README.md) | The append-only prompt registry for the prompt experiments. It is not part of the contract: `sync.py` does not vendor it |
| [search-contract-v1](search-contract-v1/README.md), [chat-contract-v1](chat-contract-v1/README.md), [chat-contract-v2](chat-contract-v2/README.md) | The search and chat HTTP contracts (v2 is the grounded chat answer) |
| `sync.py` | Copies the contract and the agent's prompts into the agent; `--check` reports drift |
| `test_schema.py`, `test-schema.mjs` | Schema validation tests |

## Change the contract

1. Edit the files here only, then run `python sync.py` to copy them into the agent. `python sync.py --check` reports drift.
2. Bump `VERSION` and update every consumer in the same PR. A taxonomy change also needs a migration.
3. Update the request goldens the change touches ([Changing a request](golden/README.md#changing-a-request)): the P1 and RP1 cases reference the contract files by sha256.
4. Adopting an experiment prompt in production is a separate decision with a version bump.

## Read more

- [Analysis schema](../.docs/analysis-schema.md): how the contract is validated, repaired and stored
- [VM API contracts](../.docs/vm-api-contracts.md): the agent routes the search and chat contracts describe
