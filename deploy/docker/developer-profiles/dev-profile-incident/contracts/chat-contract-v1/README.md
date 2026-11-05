<!--
agents:
  read-when: Changing or validating the request or response of POST /api/v1/incidents/chat.
  owns: the JSON Schemas and fixtures of chat-contract-v1.
  rules: Update the fixtures, ../test_schema.py and every consumer in the same PR as a schema change.
  check: pytest ../test_schema.py -k chat
-->

# Chat contract v1

JSON Schemas and fixtures for `POST /api/v1/incidents/chat`, the evidence Q&A route of `vss-agent` and the mock (`chat-contract-v1`). The grounded answer extends it in [chat contract v2](../chat-contract-v2/README.md).

## What is inside

| File | What it is |
|---|---|
| [chat_request.schema.json](chat_request.schema.json) | The request schema |
| [chat_response.schema.json](chat_response.schema.json) | The response schema |
| [fixtures/](fixtures) | Valid and invalid example requests and responses |
| [VERSION](VERSION) | The contract version |

## Read more

- [VM API contracts: Incident chat](../../.docs/vm-api-contracts.md#post-apiv1incidentschat): the fields and behaviour of the route
