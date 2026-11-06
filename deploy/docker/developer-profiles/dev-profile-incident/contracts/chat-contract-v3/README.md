<!--
agents:
  read-when: Changing or validating the routed answer of POST /api/v1/incidents/chat.
  owns: the JSON Schemas and fixtures of chat-contract-v3, and the meaning of its extra response fields.
  rules: Update the fixtures, ../test_schema.py and every consumer in the same PR as a schema change. The request schema stays equal to v1 apart from its id.
  check: pytest ../test_schema.py -k chat
-->

# Chat contract v3

The routed answer of `POST /api/v1/incidents/chat` when the agent runs with `INCIDENT_CHAT_MODE=routed` (`chat-contract-v3`). A template answer (the default) keeps the [v1](../chat-contract-v1/README.md) shape, and a grounded answer the [v2](../chat-contract-v2/README.md) shape.

## What the response adds to v2

- `message.source`: `report` (composed by code) or `report_llm` (read from the report by the chat model). A fresh video look is not a chat answer: it comes from its own route.
- `message.video_offer`: `{reason, from_seconds?}`, present only when the agent has video checks on and a check could help. It never runs without the reviewer's confirmation.
- `grounding.route`: `deterministic`, `report_llm` or `insufficient`; `grounding.route_reason` says why.
- `message.citations` on an insufficient answer: unlike v2 it is not always empty. An item the answer itself names from the report keeps its card, because a model often flags a useful partial answer as insufficient.
- `grounding.unknown_times`: times in the answer that the report does not hold. A client must not link them.
- `grounding.model` is `null` when no model answered, and `grounding.mode` may be `routed`.

## Read more

- [VM API contracts: Incident chat](../../.docs/vm-api-contracts.md#post-apiv1incidentschat): how the route behaves
- [Prompt registry](../prompts/README.md): the system prompt is `chat/incident-routed`
