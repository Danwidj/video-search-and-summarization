# Chat Contract v1 (`chat-contract-v1`)

Defines the request and response contract for the natural-language incident evidence chat endpoint:
`POST /api/v1/incidents/chat`

## Background & Scope

Part of MVP2 (natural-language evidence search and conversational intelligence for `dev-profile-incident`).
The contract aligns the mock backend (`mock-backend/base_profile_mock`), the native VM chat service (`services/agent`), `incident-console-v2` (PR 118), and retrieval evaluation.

### Key Decisions & Grounding Rules
- **Conversational Q&A:** Allows multi-turn questions about incidents, entities, instruments, and assets across global or incident-specific contexts.
- **Search-Grounded Citations:** The assistant response includes structured citations to retrieved evidence items, each with `incident_id`, `item_id`, `item_type`, `timestamp_seconds`, and `crop_image_url`.
- **Jump-to-Clip & Crop Inspection:** Each citation carries `timestamp_seconds` and `crop_image_url` so UI clients can render visual evidence cards and seek the video player directly to the exact moment.
- **Clean Empty & Error Handling:** When no relevant evidence is found, the assistant returns a clean grounded message with `citations: []`. Invalid requests return descriptive HTTP 400/422 responses.

- **Revision-scoped chat:** An optional `version_id` (a `report_revisions.id`) asks about one report revision, and an optional `draft_report` (requires `version_id`) asks about unsaved edits to it. The official revision is answered from the search index (`evidence_crops`); any other revision, and any draft, is answered from that revision's own saved `evidence`, because `evidence_crops` holds official revisions only. A draft's items come from the draft, with each crop taken from the same item in `version_id`'s evidence (empty `crop_image_url` when that item is new). The response shape is unchanged.

## Schema Files

- [`chat_request.schema.json`](./chat_request.schema.json): JSON schema for `POST /api/v1/incidents/chat` request bodies.
- [`chat_response.schema.json`](./chat_response.schema.json): JSON schema for `POST /api/v1/incidents/chat` response bodies.

## Fixtures

- `fixtures/valid/`:
  - `minimal-request.json`: Only the required `messages` array.
  - `full-request.json`: All request fields including `session_id`, `messages`, and `context` (`scope`, `incident_id`, `evidence_crop_ids`).
  - `empty-response.json`: Valid assistant response with zero citations.
  - `full-response.json`: Grounded assistant response with multiple evidence citations.
  - `version-request.json`: A question about one revision (`version_id`).
  - `draft-request.json`: A question about an unsaved draft report (`version_id` and `draft_report`).
- `fixtures/invalid/`:
  - `request-missing-messages.json`: Request without required `messages`.
  - `request-empty-messages.json`: Request with empty `messages` array.
  - `request-invalid-scope.json`: Context scope not in `["global", "incident"]`.
  - `request-draft-without-version.json`: `draft_report` without `version_id`.
  - `request-invalid-version-id.json`: `version_id` below 1.
  - `response-missing-session.json`: Response missing `session_id`.
  - `response-invalid-role.json`: Message role not `"assistant"`.
  - `response-invalid-citation.json`: Citation missing required fields (e.g. `crop_image_url`, `timestamp_seconds`).
