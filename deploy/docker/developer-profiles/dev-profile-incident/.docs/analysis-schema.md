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
| `title` | `str` | Text | `""` | Short descriptive title of the incident |
| `incident_type` | `str` | `str`; taxonomy (`road accident`, `burglary`, `explosion`, `fighting`, `animal`) requested by prompt, not model-validated | `"road accident"` | Classification |
| `severity` | `int` | Integer, `1 <= severity <= 5` | `1` | Overall incident severity score |
| `severity_reason` | `str` | Text | `""` | Justification and visible evidence supporting the severity score |
| `confidence` | `float` | Float, `0.0 <= confidence <= 1.0` | `0.0` | Model confidence in the classification and report |
| `incident_start` | `str` | Timestamp string (`"M:SS"` or `"H:MM:SS"`) | `"0:00"` | Timestamp marking onset; prompt forbids LLM from filling — derived from `[Xs-Ys]` markers (`"0:00"` if none) |
| `incident_end` | `str` | Timestamp string (`"M:SS"` or `"H:MM:SS"`) | `"0:00"` | Timestamp marking resolution; prompt forbids LLM from filling — derived from `[Xs-Ys]` markers (`"0:00"` if none) |
| `incident_start_confirmed` | `bool` | Boolean | `False` | Whether onset time is conclusively identified in footage (set `True` when valid `[Xs-Ys]` markers exist) |
| `duration_seconds` | `int | None` | `int or None, unconstrained`; derived as `max(0, round(span_end - span_start))` from `[Xs-Ys]` markers when LLM gives None | `None` | Calculated or estimated incident duration |
| `description` | `str` | Text | `""` | Comprehensive narrative description of the incident |
| `persons` | `list[Person]` | List of `Person` objects | `[]` | Identified persons and actors (empty list valid) |
| `instruments` | `list[Instrument]` | List of `Instrument` objects | `[]` | Tools, weapons, and objects observed |
| `assets` | `list[Asset]` | List of `Asset` objects | `[]` | Impacted or involved property, vehicles, or structures |
| `timeline` | `list[TimelineItem]` | List of `TimelineItem` objects | `[]` | Chronological sequence of event milestones |
| `uncertainties` | `list[str]` | List of strings | `[]` | Explicit ambiguities, blind spots, or occluded details |
| `location` | `str` | Text | `""` | Inferred or observed setting (e.g. `indoor warehouse`, `parking lot`) |

---

## 2. Field Mapping & Translator Divergence

The Next.js console (`incident-console-v2`) defines an alternate camelCase schema in TypeScript/Zod (`incident-console-v2/lib/analysis/schema.ts`: `incidentAnalysisSchema`). `vlm-gateway` is a schema-less Python passthrough proxy (`vlm-gateway/app.py`); in gateway mode v2 parses and validates the VLM output itself via `parseIncidentAnalysis`. Furthermore, `incident-console-v2/app/api/analysis/route.ts` implements runtime translator logic (`analyzeViaAgent`) to convert the native agent's output into the console's shape.

The table below contrasts the reference agent fields, the console v2 fields, the translation logic, and every documented discrepancy.

| Reference Field (`services/agent`) | Console v2 Field (`incident-console-v2/lib/analysis/schema.ts`) | Translation in `incident-console-v2/app/api/analysis/route.ts` (`analyzeViaAgent`) | Mismatch & Divergence Notes |
|---|---|---|---|
| `title` (`str`, def `""`) | `title` (`string`, def `'Untitled Incident'`, max 160) | `(agentPayload.title \|\| '').trim() \|\| 'Incident Report'` | **Default mismatch:** Agent defaults to empty string; Console defaults to `'Untitled Incident'` (fallback `'Incident Report'` in translation). Console enforces 160 character limit. |
| `incident_type` (`str`, def `"road accident"`) | `incidentType` (`string`, def `'other'`, max 32) | `(agentPayload.incident_type \|\| '').trim() \|\| 'other'` | **Naming & Default mismatch:** Snake_case vs camelCase. Agent taxonomy default is `"road accident"` (`INCIDENT_TYPES[0]`); Console default is `'other'` with max 32 chars. |
| `description` (`str`, def `""`) | `summary` (`string`, def `""`) | `(agentPayload.description \|\| agentPayload.summary \|\| '').trim() \|\| 'No incident summary available.'` | **Naming mismatch:** Agent names this `description`; Console names this `summary`. Translator accepts either `description` or `summary` (note: agent never returns `summary`, so that fallback is dead in practice). |
| `severity` (`int`, 1–5, def `1`) | `severityLevel` (`number`, 1–5, def `1`) | `Math.min(5, Math.max(1, Math.round(agentPayload.severity ?? 1)))` | **Naming & Rounding mismatch:** Snake_case `severity` vs camelCase `severityLevel`. Translator rounds and clamps to 1–5; Console Zod schema floors numeric inputs and also supports string coercion (`"critical"` -> 5, `"high"` -> 4, etc.). |
| `severity_reason` (`str`, def `""`) | `severityReason` (`string`, def `'Severity determined from visible evidence.'`) | `(agentPayload.severity_reason \|\| '').trim() \|\| 'Assessed by agent.'` | **Naming & Default mismatch:** CamelCase in console. Differing default fallback strings when empty. |
| `confidence` (`float`, 0.0–1.0, def `0.0`) | `confidenceScore` (`number`, 0.0–1.0, def `0.5`) | `typeof agentPayload.confidence === 'number' ? Math.min(1, Math.max(0, agentPayload.confidence)) : 0` | **Naming & Default mismatch:** Snake_case `confidence` vs camelCase `confidenceScore`. Agent defaults to `0.0`; Console Zod defaults to `0.5`. (Console clamps and normalizes percentages > 1). |
| `incident_start` (`str`, def `"0:00"`) | `startTimestamp` (`string \| null`, def `null`) | `agentPayload.incident_start?.trim() \|\| null` | **Naming & Type mismatch:** Agent uses `"0:00"` string default (derived from `[Xs-Ys]`); Console uses nullable string defaulting to `null`. |
| `incident_end` (`str`, def `"0:00"`) | `endTimestamp` (`string \| null`, def `null`) | `agentPayload.incident_end?.trim() \|\| null` | **Naming & Type mismatch:** Agent uses `"0:00"` string default (derived from `[Xs-Ys]`); Console uses nullable string defaulting to `null`. |
| `incident_start_confirmed` (`bool`, def `False`) | *(None)* | *(Dropped)* | **Field dropped:** Agent tracks whether onset timestamp is confirmed; Console v2 schema does not represent this field. |
| `duration_seconds` (`int \| None`, def `None`) | `durationSeconds` (`number \| null`, def `null`) | `typeof agentPayload.duration_seconds === 'number' && agentPayload.duration_seconds >= 0 ? Math.round(agentPayload.duration_seconds) : null` | **Naming & Coercion mismatch:** Snake_case vs camelCase. Translator keeps 0 (unlike falsy `|| null` checks); Zod's `coerceNonNegativeNumberOrNull` then applies `Math.floor`. |
| `persons` (`list[Person]`, def `[]`) | `entities` (`array`, def `[]`) | Maps `persons` to `{ type: 'human', description: "${person.description}: ${person.actions}" }` | **Structural divergence:** Agent has explicit `persons` model (with `description` and `actions`). Console has generalized `entities` array supporting `type: 'human' \| 'animal' \| 'unknown'`. In translation, agent `persons` are collapsed into `entities` with `type: 'human'`. Translator checks `agentPayload.entities` first, but the agent's `response_model=IncidentReport` never returns `entities`, making that branch dead. (In gateway mode, Zod's `mapEntityType` maps `person` to `'unknown'`). |
| `instruments` (`list[Instrument]`) | `instruments` (`array`, def `[]`) | Maps items: `name`, `description`, `threat_level` -> `threatLevel` | **Naming & Clamping mismatch:** Nested `threat_level` is converted to camelCase `threatLevel`. Translator rounds and clamps to 1–5; Zod floors and turns out-of-range values to null; Agent Pydantic model maps <1 to None and clamps >5 to 5. |
| `assets` (`list[Asset]`) | `assets` (`array`, def `[]`) | Maps items: `name`, `description` | **Aligned:** Sub-fields identical (`name`, `description`). |
| `timeline` (`list[TimelineItem]`) | `timeline` (`array`, def `[]`) | Maps items: `start_seconds` -> `startSeconds`, `end_seconds` -> `endSeconds`, `description` | **Naming & Precision mismatch:** Translator maps `startSeconds` (`Math.max(0, item.start_seconds)`) and `endSeconds` (`Math.max(0, item.end_seconds)`). Zod's schema then floors both to integers, losing sub-second precision; agent allows raw floats. |
| `uncertainties` (`list[str]`, def `[]`) | `uncertainties` (`array`, def `[]`) | Filters and trims non-empty strings | **Aligned:** String array representation identical. |
| `location` (`str`, def `""`) | *(None)* | *(Dropped)* | **Field dropped:** Agent captures general scene/location setting (`location: str = ""`); Console v2 schema omits location entirely. |

### Additional Mismatch Details

1. **Timeline Integer Flooring:** Zod's schema (`schema.ts: coerceNonNegativeNumberOrNull`) floors `startSeconds` and `endSeconds` to integers (`Math.floor`), losing sub-second precision. The translator clamps both to `Math.max(0, ...)`, whereas the agent's Pydantic model permits unconstrained floats.
2. **Severity and Threat Level Mapping:** The translator rounds severity and threat level and clamps both to 1–5 (`Math.min(5, Math.max(1, Math.round(...)))`). Zod floors numeric inputs; `mapThreatLevel` turns out-of-range values into `null`, whereas the agent's validator maps `< 1` to `None` and clamps `> 5` to `5`.
3. **Entities Fallbacks:** The translator checks `agentPayload.entities` first (mapping `person` -> `human`) and falls back to `agentPayload.persons`. Because the agent's `response_model=IncidentReport` only has `persons`, the `entities` branch is dead in practice. Furthermore, in direct gateway mode, Zod's `mapEntityType` maps unrecognized strings like `"person"` to `"unknown"`.
4. **Summary Fallback:** The translator's `agentPayload.summary` fallback is dead, because the agent's schema only defines `description`.

---

### Agent Mode Double-Write Architecture

When `incident-console-v2` executes in **Agent Mode** (invoking the `vss-agent` container via `POST /api/v1/incident/analyze`), database persistence occurs in two distinct stages across different processes:

1. **Agent Self-Persistence (`services/agent/src/vss_agents/tools/incident_report_gen.py:_persist_incident`):**
   - Directly writes `videos`: `filepath = report_result.video_url` (temporary VST streaming URL) and `duration = NULL`.
   - Writes `model_runs`: `model_name = 'incident_report_gen'` (configurable default) and `notes = NULL`.
   - Executes atomic stored procedure `insert_incident(...)` with native agent values: `type` (unvalidated string), `start_timestamp`/`end_timestamp` (`"M:SS"`), `duration`, `description`, `severity_level`, and `confidence_score`.
   - Inserts child evidence rows:
     - `entities`: id = `e` + 19 hex of sha256(`incident_id:idx`), `type = 'person'`, and `description = f"{person.description} {person.actions}".strip()`.
     - `instruments`: id = `i` + 19 hex of sha256(`incident_id:idx`), name, description, threat_level.
     - `assets`: id = `a` + 19 hex of sha256(`incident_id:idx`), name, description.
2. **Console v2 Post-Processing (`incident-console-v2/app/api/analysis/route.ts:analyzeViaAgent`):**
   - Overwrites `model_runs`: sets `model_name = 'vss-agent'` (because the agent's HTTP response model does not expose `model_name`), sets `notes` to serialized JSON (`{"incidentConsoleV2": {report, rawModelOutput, normalizedModelOutput}}`), and updates `run_datetime`.
   - Re-upserts `videos.filepath` with the durable Cloudflare R2 key, restoring it from the transient VST URL.
   - Inserts `reports` record pointing to the model run.

> [!IMPORTANT]
> Because of this double-write architecture, the translated camelCase report exists **only** inside `model_runs.notes` JSON and in the HTTP response. The relational database rows in `incidents`, `entities`, `instruments`, and `assets` hold the untranslated, native agent values.

---

### Extraction Validation Failure Handling

In `services/agent/src/vss_agents/tools/incident_report_gen.py:_extract_structured_report`, structured output is extracted from the model's text generation:

- **Visibility & Error Surfacing:** If the model fails to return valid JSON, schema validation fails (`pydantic.ValidationError`, such as severity out of bounds), or extraction times out, `_extract_structured_report` logs an `ERROR`-level message and raises `ValueError` (for invalid output) or `TimeoutError`.
- **HTTP Status Codes:** `services/agent/src/vss_agents/api/incident_analyze.py` catches these exceptions and surfaces them directly to the client as **HTTP 422 (Unprocessable Entity)** or **HTTP 504 (Gateway Timeout)**.
- **Persistence Aborted:** Raising on extraction failure prevents `_persist_incident` from executing, ensuring invalid or fallback dummy data (`"road accident"`, severity 1, confidence 0.0) is never persisted to the database.

---

## 3. Database Persistence Mapping

### Primary Incident Record (`incidents` table)

When persisting an `IncidentReport` to the Supabase PostgreSQL database, `services/agent/src/vss_agents/tools/incident_report_gen.py`
maps the extraction-facing Pydantic model names to the SQL column names expected by `insert_incident`
per `deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py`:

| Pydantic Model Field (`IncidentReport`) | Database Column (`incidents` table) | Stored Format / Notes |
|---|---|---|
| `incident_type` | `type` | `VARCHAR(32)` (free text, unconstrained) |
| `incident_start` | `start_timestamp` | `VARCHAR(32)` (`"M:SS"` or `"H:MM:SS"`) |
| `incident_end` | `end_timestamp` | `VARCHAR(32)` (`"M:SS"` or `"H:MM:SS"`) |
| `duration_seconds` | `duration` | `INTEGER` |
| `description` | `description` | `TEXT` |
| `severity` | `severity_level` | `INTEGER` |
| `confidence` | `confidence_score` | `DOUBLE PRECISION` (updated from single-precision `REAL` in migration `20260925031000`) |

### Child Evidence Persistence Mapping

The agent persists observed actors, tools, and impacted property into their respective relational tables:

| Model Sub-List | Target Table | Primary Key (`*_id`) Generation | Stored Attributes / Notes |
|---|---|---|---|
| `persons` | `entities` | `'e' + sha256(f"{incident_id}:{idx}")[:19]` | `type = 'person'` (VARCHAR(16)), `description = f"{person.description} {person.actions}".strip()`. `image` is NULL. |
| `instruments` | `instruments` | `'i' + sha256(f"{incident_id}:{idx}")[:19]` | `name`, `description`, `threat_level` (INTEGER 1–5 or NULL). `image` is NULL. |
| `assets` | `assets` | `'a' + sha256(f"{incident_id}:{idx}")[:19]` | `name`, `description`. `image` is NULL. |

### Unpersisted Fields

The following fields in `IncidentReport` and Console v2 schemas have **no corresponding database columns** in PostgreSQL:

- `title`
- `severity_reason`
- `timeline`
- `uncertainties`
- `location`
- `incident_start_confirmed`

**Storage behavior:** In Gateway Mode, these fields survive within `model_runs.notes` JSON. In Agent Mode, `location` and `incident_start_confirmed` are dropped entirely, while `title`, `severity_reason`, `timeline`, and `uncertainties` are stored in `model_runs.notes` when `incident-console-v2` updates the record.
