# Incident Analysis Schema & Output Alignment

This document defines the reference schema for automated incident analysis reports and provides a
comprehensive mapping between the reference agent model (`services/agent/`) and the console /
gateway representation (`incident-console-v2/`).

> [!NOTE]
> This document is descriptive of the codebase as it exists today. It documents discrepancies and
> translation behavior for implementers and AI agents. It does not alter runtime code.

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
| `threat_level` | `int | None` | Integer, `1 <= threat_level <= 5`, or `None` | `None` | Assessed threat rating (coerced and clamped via validator) |

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
| `start_seconds` | `float` | `>= 0.0` | `0.0` | Offset in seconds from video start when the event begins |
| `end_seconds` | `float | None` | `>= start_seconds`, or `None` | `None` | Offset in seconds when the event concludes |
| `description` | `str` | Text | `""` | Concise description of the event occurring during this window |

---

### Root Model: `IncidentReport`

| Field | Type | Constraints / Range | Default | Description |
|---|---|---|---|---|
| `title` | `str` | Text | `""` | Short descriptive title of the incident |
| `incident_type` | `str` | One of: `"road accident"`, `"burglary"`, `"explosion"`, `"fighting"`, `"animal"` | `"road accident"` | Controlled taxonomy classification |
| `severity` | `int` | Integer, `1 <= severity <= 5` | `1` | Overall incident severity score |
| `severity_reason` | `str` | Text | `""` | Justification and visible evidence supporting the severity score |
| `confidence` | `float` | Float, `0.0 <= confidence <= 1.0` | `0.0` | Model confidence in the classification and report |
| `incident_start` | `str` | Timestamp string (`"M:SS"` or `"H:MM:SS"`) | `"0:00"` | Timestamp marking incident onset |
| `incident_end` | `str` | Timestamp string (`"M:SS"` or `"H:MM:SS"`) | `"0:00"` | Timestamp marking incident resolution |
| `incident_start_confirmed` | `bool` | Boolean | `False` | Whether onset time is conclusively identified in footage |
| `duration_seconds` | `int | None` | Integer `>= 0`, or `None` | `None` | Calculated or estimated incident duration |
| `description` | `str` | Text | `""` | Comprehensive narrative description of the incident |
| `persons` | `list[Person]` | List of `Person` objects | `[]` | Identified persons and actors (empty list valid) |
| `instruments` | `list[Instrument]` | List of `Instrument` objects | `[]` | Tools, weapons, and objects observed |
| `assets` | `list[Asset]` | List of `Asset` objects | `[]` | Impacted or involved property, vehicles, or structures |
| `timeline` | `list[TimelineItem]` | List of `TimelineItem` objects | `[]` | Chronological sequence of event milestones |
| `uncertainties` | `list[str]` | List of strings | `[]` | Explicit ambiguities, blind spots, or occluded details |
| `location` | `str` | Text | `""` | Inferred or observed setting (e.g. `indoor warehouse`, `parking lot`) |

---

## 2. Field Mapping & Translator Divergence

The Next.js frontend (`incident-console-v2`) and the `vlm-gateway` process define an alternate schema
using TypeScript and Zod (`incident-console-v2/lib/analysis/schema.ts`: `incidentAnalysisSchema`).
Furthermore, `incident-console-v2/app/api/analysis/route.ts` implements runtime translator logic
(`analyzeViaAgent`) to convert the native agent's output into the console's shape.

The table below contrasts the reference agent fields, the console v2 fields, the translation logic,
and every documented discrepancy.

| Reference Field (`services/agent`) | Console v2 Field (`lib/analysis/schema.ts`) | Translation in `route.ts` (`analyzeViaAgent`) | Mismatch & Divergence Notes |
|---|---|---|---|
| `title` (`str`, def `""`) | `title` (`string`, def `'Untitled Incident'`, max 160) | `(agentPayload.title \|\| '').trim() \|\| 'Incident Report'` | **Default mismatch:** Agent defaults to empty string; Console defaults to `'Untitled Incident'` (fallback `'Incident Report'` in translation). Console enforces 160 character limit. |
| `incident_type` (`str`, def `"road accident"`) | `incidentType` (`string`, def `'other'`, max 32) | `(agentPayload.incident_type \|\| '').trim() \|\| 'other'` | **Naming & Default mismatch:** Snake_case vs camelCase. Agent taxonomy default is `"road accident"` (`INCIDENT_TYPES[0]`); Console default is `'other'` with max 32 chars. |
| `description` (`str`, def `""`) | `summary` (`string`, def `""`) | `(agentPayload.description \|\| agentPayload.summary \|\| '').trim() \|\| 'No incident summary available.'` | **Naming mismatch:** Agent names this `description`; Console names this `summary`. Translator accepts either `description` or `summary`. |
| `severity` (`int`, 1–5, def `1`) | `severityLevel` (`number`, 1–5, def `1`) | `Math.min(5, Math.max(1, Math.round(agentPayload.severity ?? 1)))` | **Naming mismatch:** Snake_case `severity` vs camelCase `severityLevel`. Console Zod schema also supports string coercion (`"critical"` -> 5, `"high"` -> 4, etc.). |
| `severity_reason` (`str`, def `""`) | `severityReason` (`string`, def `'Severity determined from visible evidence.'`) | `(agentPayload.severity_reason \|\| '').trim() \|\| 'Assessed by agent.'` | **Naming & Default mismatch:** CamelCase in console. Differing default fallback strings when empty. |
| `confidence` (`float`, 0.0–1.0, def `0.0`) | `confidenceScore` (`number`, 0.0–1.0, def `0.5`) | `typeof agentPayload.confidence === 'number' ? Math.min(1, Math.max(0, agentPayload.confidence)) : 0` | **Naming & Default mismatch:** Snake_case `confidence` vs camelCase `confidenceScore`. Agent defaults to `0.0`; Console Zod defaults to `0.5`. (Console clamps and normalizes percentages > 1). |
| `incident_start` (`str`, def `"0:00"`) | `startTimestamp` (`string \| null`, def `null`) | `agentPayload.incident_start?.trim() \|\| null` | **Naming & Type mismatch:** Agent uses `"0:00"` string default; Console uses nullable string defaulting to `null`. |
| `incident_end` (`str`, def `"0:00"`) | `endTimestamp` (`string \| null`, def `null`) | `agentPayload.incident_end?.trim() \|\| null` | **Naming & Type mismatch:** Agent uses `"0:00"` string default; Console uses nullable string defaulting to `null`. |
| `incident_start_confirmed` (`bool`, def `False`) | *(None)* | *(Dropped)* | **Field dropped:** Agent tracks whether onset timestamp is confirmed; Console v2 schema does not represent this field. |
| `duration_seconds` (`int \| None`, def `None`) | `durationSeconds` (`number \| null`, def `null`) | `Math.round(agentPayload.duration_seconds) \|\| null` | **Naming mismatch:** Snake_case vs camelCase. Semantics match (integer seconds or null). |
| `persons` (`list[Person]`, def `[]`) | `entities` (`array`, def `[]`) | Maps `persons` to `{ type: 'human', description: "${person.description}: ${person.actions}" }` | **Structural divergence:** Agent has explicit `persons` model (with `description` and `actions`). Console has generalized `entities` array supporting `type: 'human' \| 'animal' \| 'unknown'`. In translation, agent `persons` are collapsed into `entities` with `type: 'human'`. |
| `instruments` (`list[Instrument]`) | `instruments` (`array`, def `[]`) | Maps items: `name`, `description`, `threat_level` -> `threatLevel` | **Naming mismatch:** Nested `threat_level` is converted to camelCase `threatLevel`. |
| `assets` (`list[Asset]`) | `assets` (`array`, def `[]`) | Maps items: `name`, `description` | **Aligned:** Sub-fields identical (`name`, `description`). |
| `timeline` (`list[TimelineItem]`) | `timeline` (`array`, def `[]`) | Maps items: `start_seconds` -> `startSeconds`, `end_seconds` -> `endSeconds`, `description` | **Naming mismatch:** Nested snake_case timing properties mapped to camelCase. |
| `uncertainties` (`list[str]`, def `[]`) | `uncertainties` (`array`, def `[]`) | Filters and trims non-empty strings | **Aligned:** String array representation identical. |
| `location` (`str`, def `""`) | *(None)* | *(Dropped)* | **Field dropped:** Agent captures general scene/location setting (`location: str = ""`); Console v2 schema omits location entirely. |

---

## 3. Database Column Translation (`services/agent/src/vss_agents/utils/incident_db.py`)

When persisting an `IncidentReport` to the Supabase PostgreSQL database, `services/agent/src/vss_agents/tools/incident_report_gen.py`
maps the extraction-facing Pydantic model names to the SQL column names expected by `insert_incident`
per `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py`:

| Pydantic Model Field (`IncidentReport`) | Database Column (`incidents` table) | Stored Format / Notes |
|---|---|---|
| `incident_type` | `type` | `VARCHAR(32)` |
| `incident_start` | `start_timestamp` | `VARCHAR(32)` |
| `incident_end` | `end_timestamp` | `VARCHAR(32)` |
| `duration_seconds` | `duration` | `INTEGER` |
| `description` | `description` | `TEXT` |
| `severity` | `severity_level` | `INTEGER` |
| `confidence` | `confidence_score` | `REAL` / `FLOAT` |

This mapping is performed in `incident_report_gen.py` before invoking `IncidentDB.insert_incident()`.
