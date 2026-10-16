# Incident Contract v3 (`incident-contract-v3`)

Defines the structured incident extraction schema shared by eval, incident-console-v2 and vss-agent.

## Background & Scope

Part of MVP2 (natural-language evidence search with object crops for `dev-profile-incident`).
The contract aligns the VLM extraction prompt, JSON schema, and P1 settings.

### Key Decisions & Pilot Adjustments

- **Pilot spatial grounding finding:** The VLM bounding box accuracy pilot revealed that while VLMs fail at coordinate regression (0% well-framed), temporal grounding is highly accurate (>95% of timestamps land on the correct frame). Therefore, `incident-contract-v3` supplies `timestamp_seconds` and a short detector `label` for each entity, instrument, and asset.

- **Bounding boxes:** No `bounding_box` in the report schema. Spatial bounding boxes are detector-produced and optional in search hits (`search-contract-v1`), not VLM outputs.

- **Always-on Critic:** Every hit includes a `critic` verdict (`confirmed`, `rejected`, `unverified`) with rationale and confidence score.

- **Jump-to-Clip:** Each item carries `timestamp_seconds` for jump-to-clip functionality.

## Schema Files

- [`incident_report.schema.json`](./incident_report.schema.json): JSON schema for structured incident extraction. Entities, instruments, and assets require `timestamp_seconds` (integer >= 0) and `label` (short detector string). No `bounding_box`.

- [`incident_extraction_prompt.md`](../../../../incident_extraction_prompt.md): Canonical VLM extraction prompt with grounding section (Section 9).

- `VERSION`: Contract version identifier.

## Fixtures

- `fixtures/valid/`: Valid incident report examples
- `fixtures/invalid/`: Invalid report examples (schema validation failures)

## Versioning

- `incident-contract-v1`: Initial report schema (no temporal grounding, no detector labels)
- `incident-contract-v2`: Added severity rubric and timeline
- `incident-contract-v3`: Added required `timestamp_seconds` and `label` to entities/instruments/assets; removed `bounding_box`; added grounding section to prompt