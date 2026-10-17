# Search Contract v1 (`search-contract-v1`)

Defines the request and response contract for the natural-language incident evidence search endpoint:
`POST /api/v1/incidents/search`

## Background & Scope

Part of MVP2 (natural-language evidence search with object crops for `dev-profile-incident`).
The contract aligns the mock backend (`mock-backend/base_profile_mock`), the native VM search service (`services/agent`), `incident-console-v2` (PR 118), retrieval eval (PR 119), and Supabase pgvector search (PR 126).

### Key Decisions & Pilot Adjustments
- **Pilot spatial grounding finding:** The VLM bounding box accuracy pilot revealed that while VLMs fail at coordinate regression (0% well-framed), temporal grounding is highly accurate (>95% of timestamps land on the correct frame). Therefore, `incident-contract-v3` supplies `timestamp_seconds` and a short detector `label`.
- **Bounding boxes:** In `search-contract-v1`, `hit.item.bounding_box` is optional/nullable (`[ymin, xmin, ymax, xmax]` normalized to 0-1000). Any bounding box is detector-produced (e.g. Grounding DINO / OWLv2), never a direct VLM output.
- **Always-on Critic:** Every returned hit includes a `critic` verdict (`confirmed`, `rejected`, `unverified`) with rationale and confidence score.
- **Jump-to-Clip:** Each hit carries `item.timestamp_seconds` and parent `incident.playback_url` and `incident.incident_window` so the UI can immediately jump to the moment of interest.

## Schema Files

- [`search_request.schema.json`](./search_request.schema.json): JSON schema for `POST /api/v1/incidents/search` request bodies.
- [`search_response.schema.json`](./search_response.schema.json): JSON schema for `POST /api/v1/incidents/search` response bodies.

## Fixtures

- `fixtures/valid/`:
  - `minimal-request.json`: Only the required `query` field.
  - `full-request.json`: All request fields including `top_k`, `min_similarity`, and `filters` (including `item_types`).
  - `empty-response.json`: Valid response with zero hits.
  - `full-response.json`: Populated response with multiple hits (entities, instruments, assets), crop image URLs, critic verdicts, and parent incident metadata.
- `fixtures/invalid/`:
  - `request-missing-query.json`: Request without required `query`.
  - `request-invalid-top-k.json`: `top_k` exceeding bounds (> 50 or < 1).
  - `request-invalid-item-type.json`: Item type not in `["entity", "instrument", "asset"]`.
  - `response-missing-critic.json`: Hit missing required `critic` block.
  - `response-invalid-verdict.json`: Hit with invalid critic verdict enum value.
  - `response-negative-timestamp.json`: Hit with negative `timestamp_seconds`.
