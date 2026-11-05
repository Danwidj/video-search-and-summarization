<!--
agents:
  read-when: Changing or validating the grounded answer of POST /api/v1/incidents/chat.
  owns: the JSON Schemas and fixtures of chat-contract-v2, and the meaning of its extra response fields.
  rules: Update the fixtures, ../test_schema.py and every consumer in the same PR as a schema change. The request schema stays equal to v1 apart from its id.
  check: pytest ../test_schema.py -k chat
-->

# Chat contract v2

The grounded answer of `POST /api/v1/incidents/chat` when the agent runs with `INCIDENT_CHAT_MODE=grounded` (`chat-contract-v2`). A chat model answers an incident question from one report version: the asked one, the official one, or a reviewer's unsaved draft. A template-mode answer (the default) keeps the [v1](../chat-contract-v1/README.md) shape exactly.

## What is inside

| File | What it is |
|---|---|
| [chat_request.schema.json](chat_request.schema.json) | The request schema: the same fields as v1, which a test enforces |
| [chat_response.schema.json](chat_response.schema.json) | The response schema: the v1 answer plus the fields below |
| [fixtures/](fixtures) | Valid and invalid example responses |

## What the response adds

- `message.insufficient_evidence`: the report cannot answer, or contradicts the question's premise. Citations are then empty.
- `grounding`: `{mode, scope, model, version_id, official, draft, dropped_citations, ids_resolved, prompt_sha256, usage}`.
- `grounding.ids_resolved`: the ids (item ids, and incident ids in a library answer) the model wrote although the question did not ask for ids. Each was replaced by the description of what it names.

A library question adds these to `grounding`:
- `plan`, `matching`, `count_exact`, `candidates` and `plan_prompt_sha256`;
- `answered_by`: `code` for a count or breakdown, else `model`;
- `versions`: each incident's report version;
- `incident_titles`: each shown incident's type and title, keyed by id;
- `item_names`: each cited item's name, keyed by `incident_id/item_id`.

In a library answer `version_id` and `official` are `null`, and `prompt_sha256` is present only when the model answered.

## Read more

- [VM API contracts: Incident chat](../../.docs/vm-api-contracts.md#post-apiv1incidentschat): how the route behaves
- [Prompt registry](../prompts/README.md): the system prompt is `chat/incident-answer`
