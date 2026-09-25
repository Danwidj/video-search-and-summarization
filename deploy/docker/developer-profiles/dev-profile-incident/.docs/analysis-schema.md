# Incident Analysis Schema & Output Alignment

This document defines the unified schema for automated incident analysis reports and provides the
contract specification shared between the reference agent model (`services/agent/`) and the console /
gateway implementation (`incident-console-v2/`).

> [!NOTE]
> As of 2026-09-25, the analysis contract across Gateway Mode (local) and Agent Mode (VM) is unified
> on the native `snake_case` schema defined by `vss-agent` and validated by `incident-console-v2`.

---

## 1. Reference Incident Report Schema

The authoritative reference format is defined in Python using Pydantic in
`services/agent/src/vss_agents/data_models/incident_report.py`. All fields adhere to standard
Python `snake_case` naming conventions.

### Sub-Models

#### `Person`
Represents an individual person or actor observed during the incident footage.

| Field | Type | Constraints / Range | Default | Description |
|---|---|---|---|---|
| `description` | `str` | Text | `""` | Visual appearance, clothing, identifiers, or physical traits |
| `actions` | `str` | Text | `""` | Specific actions, movement, or behaviors exhibited |

#### `Instrument`
Represents an object, tool, or weapon observed in connection with the incident.

| Field | Type | Constraints / Range | Default | Description |
|---|---|---|---|---|
| `name` | `str` | Text | `""` | Identifier or category (e.g. `crowbar`, `knife`, `lighter`) |
| `description` | `str` | Text | `""` | Contextual usage or handling description |
| `threat_level` | `int | None` | Integer 1–5 or `None`; before-validator rounds numeric input, maps <1 / bool / non-numeric to None, clamps >5 to 5 | `None` | Assessed threat rating |

#### `Asset`
Represents physical property, infrastructure, equipment, or vehicles impacted by or involved in the incident.

| Field | Type | Constraints / Range | Default | Description |
|---|---|---|---|---|
| `name` | `str` | Text | `""` | Identifier (e.g. `front entrance glass`, `cash register`, `silver sedan`) |
| `description` | `str` | Text | `""` | Observed damage, state, or location context |

#### `TimelineItem`
Represents a discrete chronological event or phase within the incident.

| Field | Type | Constraints / Range | Default | Description |
|---|---|---|---|---|
| `start_seconds` | `float` | `float, unconstrained (expected >= 0)` | `0.0` | Offset in seconds from video start when the event begins |
| `end_seconds` | `float | None` | `float or None, unconstrained` | `None` | Offset in seconds when the event concludes |
| `description` | `str` | Text | `""` | Concise description of the event occurring during this window |

---

### Root Model: `IncidentReport`

| Field | Type | Constraints / Range | Default | Description |
|---|---|---|---|---|
| `title` | `str` | Text, max 160 characters | `""` | Short descriptive title of the incident |
| `incident_type` | `str` | `str`; taxonomy (`road accident`, `burglary`, `explosion`, `fighting`, `animal`) requested by prompt | `"road accident"` | Classification |
| `severity` | `int` | Integer, `1 <= severity <= 5` | `1` | Overall incident severity score |
| `severity_reason` | `str` | Text | `""` | Justification and visible evidence supporting the severity score |
| `confidence` | `float` | Float, `0.0 <= confidence <= 1.0` | `0.0` | Model confidence in the classification and report |
| `incident_start` | `str` | Timestamp string (`"M:SS"` or `"H:MM:SS"`) | `"0:00"` | Timestamp marking onset |
| `incident_end` | `str` | Timestamp string (`"M:SS"` or `"H:MM:SS"`) | `"0:00"` | Timestamp marking resolution |
| `incident_start_confirmed` | `bool` | Boolean | `False` | Whether onset time is conclusively identified in footage |
| `duration_seconds` | `int | None` | `int or None, unconstrained (>= 0)` | `None` | Calculated or estimated incident duration |
| `description` | `str` | Text | `""` | Comprehensive narrative description of the incident |
| `persons` | `list[Person]` | List of `Person` objects | `[]` | Identified persons and actors (empty list valid) |
| `instruments` | `list[Instrument]` | List of `Instrument` objects | `[]` | Tools, weapons, and objects observed |
| `assets` | `list[Asset]` | List of `Asset` objects | `[]` | Impacted or involved property, vehicles, or structures |
| `timeline` | `list[TimelineItem]` | List of `TimelineItem` objects | `[]` | Chronological sequence of event milestones |
| `uncertainties` | `list[str]` | List of strings | `[]` | Explicit ambiguities, blind spots, or occluded details |
| `location` | `str` | Text | `""` | Inferred or observed setting (e.g. `indoor warehouse`, `parking lot`) |

---

## 2. Unified Analysis Contract & Frontend Alignment

### Single Contract Across Both Analysis Modes

`incident-console-v2` uses the agent's native `snake_case` `IncidentReport` shape as its single analysis contract in **both** modes:

1. **Gateway Mode (`ANALYSIS_MODE=gateway`):**
   - Prompt (`incident-console-v2/lib/analysis/prompt.ts`, version `incident-v2-snake`) incorporates the agent's extraction rules and requests the exact 16-field `snake_case` JSON shape.
   - Output from the VLM gateway is parsed and validated directly with `incidentAnalysisSchema` (`incident-console-v2/lib/analysis/schema.ts`).
2. **Agent Mode (`ANALYSIS_MODE=agent`):**
   - The console invokes `POST /api/v1/incidents/{incident_id}/analyze` on `vss-agent`.
   - The native `snake_case` JSON response is parsed directly with `incidentAnalysisSchema` (no translator or camelCase conversion).
   - Full native report is saved to `model_runs.notes` and returned in the HTTP response.

### Checked-in Contract Artifact & Drift Prevention

The authoritative JSON contract specification is checked in at:
`incident-console-v2/lib/analysis/incident-report-contract.json` (contract version `incident-v2-2`).

Automated drift-prevention tests guarantee continuous parity across both environments:
- **TypeScript / Next.js Test (`incident-console-v2/tests/contract-parity.test.mjs`):** Asserts that all 16 fields, defaults, and types in `incident-report-contract.json` are accepted by `incidentAnalysisSchema` and instructed by `INCIDENT_ANALYSIS_PROMPT`.
- **Python / Agent Test (`services/agent/tests/unit_test/tools/test_incident_report_gen.py`):** Asserts that `IncidentReport.model_fields.keys()` matches `contract.fields.keys()`, enum taxonomy matches `INCIDENT_TYPES`, and prompt extraction rules match `_EXTRACTION_SYSTEM_PROMPT`.

### Tolerant Parsing Behaviors

The Zod schema (`incident-console-v2/lib/analysis/schema.ts`) mirrors the Pydantic model's constraints while retaining the resilient parsing behavior established in PR #92:
- **Threat Level Normalization:** Strings (`"3"`), words (`"high"` -> 4, `"critical"` -> 5), and floating-point values are converted to integers; values > 5 are clamped to 5; values < 1 or unparseable are coerced to `null`.
- **Severity Clamping:** Words (`"medium"` -> 3, `"critical"` -> 5) and out-of-range numbers are clamped to the 1–5 range.
- **Confidence Normalization:** Decimal percentages (e.g. `85` -> 0.85) are normalized and clamped to `0.0 <= confidence <= 1.0`.
- **String Bounds:** `title` is clamped to 160 characters; `incident_type` is trimmed to 32 characters.
- **Pass-through Unknowns:** Unrecognized fields in model responses are preserved via `.passthrough()` rather than rejecting the payload.

### Legacy DB Read-Compatibility (`model_runs.notes`)

Historical incident runs created before contract unification stored `camelCase` JSON objects in `model_runs.notes`. To maintain full backward compatibility:
- **Reader (`reportFromNotes` in `incident-console-v2/lib/reports/storage.ts`):** Transparently accepts both legacy `camelCase` notes (`severityLevel`, `summary`, `startTimestamp`, `entities`, etc.) and modern `snake_case` notes (`severity`, `description`, `incident_start`, `persons`, etc.).
- **Tolerant Schema Fallbacks:** `lib/analysis/schema.ts` provides fallback getters for legacy keys (e.g., `summary` if `description` is omitted, `entities` mapped to `persons` if `persons` is omitted).
- **Writer:** All new writes through PostgREST and Next.js routes write strictly `snake_case` payloads.

---

## 3. Database Persistence Mapping

### Primary Incident Record (`incidents` table)

When persisting an `IncidentReport` to the Supabase PostgreSQL database, both `services/agent/src/vss_agents/tools/incident_report_gen.py`
and `incident-console-v2/app/api/analysis/route.ts` map the extraction-facing fields to the SQL column names expected by `insert_incident`
per `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py`:

| Unified Model Field (`IncidentReport`) | Database Column (`incidents` table) | Stored Format / Notes |
|---|---|---|
| `incident_type` | `type` | `VARCHAR(32)` (free text, unconstrained) |
| `incident_start` | `start_timestamp` | `VARCHAR(32)` (`"M:SS"` or `"H:MM:SS"`) |
| `incident_end` | `end_timestamp` | `VARCHAR(32)` (`"M:SS"` or `"H:MM:SS"`) |
| `duration_seconds` | `duration` | `INTEGER` |
| `description` | `description` | `TEXT` |
| `severity` | `severity_level` | `INTEGER` |
| `confidence` | `confidence_score` | `DOUBLE PRECISION` (column always double precision; migration `20260925031000` widened the `insert_incident` RPC parameter `p_confidence_score` from `REAL`) |

### Child Evidence Persistence Mapping

Observed actors, tools, and impacted property are persisted into their respective relational tables:

| Model Sub-List | Target Table | Primary Key (`*_id`) Generation | Stored Attributes / Notes |
|---|---|---|---|
| `persons` | `entities` | `'e' + sha256(f"{incident_id}:{idx}")[:19]` | `type = 'person'` (VARCHAR(16)), `description = f"{person.description} {person.actions}".strip()`. `image` is NULL. |
| `instruments` | `instruments` | `'i' + sha256(f"{incident_id}:{idx}")[:19]` | `name`, `description`, `threat_level` (INTEGER 1–5 or NULL). `image` is NULL. |
| `assets` | `assets` | `'a' + sha256(f"{incident_id}:{idx}")[:19]` | `name`, `description`. `image` is NULL. |

### Unpersisted Fields

The following fields in `IncidentReport` have **no corresponding database columns** in PostgreSQL:

- `title`
- `severity_reason`
- `timeline`
- `uncertainties`
- `location`
- `incident_start_confirmed`

**Storage behavior:** In both Gateway Mode and Agent Mode, these fields are durably stored within `model_runs.notes` JSON. Displays and report review in `incident-console-v2` hydrate these fields directly from `model_runs.notes`.
