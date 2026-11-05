<!--
agents:
  read-when: Changing or validating the request or response of POST /api/v1/incidents/search.
  owns: the JSON Schemas and fixtures of search-contract-v1.
  rules: Update the fixtures, ../test_schema.py and every consumer in the same PR as a schema change.
-->

# Search contract

JSON Schemas and fixtures for `POST /api/v1/incidents/search`, the natural-language evidence search route of `vss-agent` and the mocks (`search-contract-v1`).

## What is inside

| File | What it is |
|---|---|
| [search_request.schema.json](search_request.schema.json) | The request schema |
| [search_response.schema.json](search_response.schema.json) | The response schema |
| [fixtures/](fixtures) | Valid and invalid example requests and responses |
| [VERSION](VERSION) | The contract version |

## Read more

- [VM API contracts: Incident search](../../.docs/vm-api-contracts.md#post-apiv1incidentssearch): the fields, defaults and behaviour of the route
