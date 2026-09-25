// SPDX-License-Identifier: Apache-2.0

export const INCIDENT_PROMPT_VERSION = 'incident-v2-snake';

export const INCIDENT_ANALYSIS_PROMPT = `Analyze this surveillance video and return one JSON object only.
Do not use Markdown fences and do not include commentary before or after the JSON.
Base findings only on visible evidence. Put ambiguity in uncertainties rather than inventing details.
Timestamps must be offsets from the beginning of the video.
Numeric fields must be JSON numbers, never quoted strings. For example, use "threat_level": 3, not "threat_level": "3". Use null when threat level is unknown.

Rules:
- title is a short factual title summarizing the incident (max 160 characters).
- incident_type must be exactly one of: road accident, burglary, explosion, fighting, animal.
  Pick the closest match; if nothing in the report matches any of these, use "burglary" only if there is
  a clear property-crime element, otherwise pick the single best fit from the list - never invent a new type.
- severity is an integer from 1 (minor) to 5 (critical).
- severity_reason is a concise explanation of why this severity level was selected based on observable risk or harm.
- confidence is a float from 0.0 to 1.0 reflecting how confident you are in incident_type given the video.
- incident_start: timestamp string ("M:SS" or "H:MM:SS") marking incident onset (default "0:00").
- incident_end: timestamp string ("M:SS" or "H:MM:SS") marking incident resolution (default "0:00").
- incident_start_confirmed: boolean whether onset time is conclusively identified in footage.
- duration_seconds is the duration of the incident in seconds (integer) if observable or stated, else null.
- description is a 1-3 sentence plain-language executive summary of the incident.
- persons should list each distinct person mentioned, with a short physical description and their actions.
- instruments should list objects, tools, weapons, or vehicles actively used in the incident, each with name, description of use, and optional threat_level (1-5, or null if unrated/harmless).
- assets should list property, structures, vehicles, or items affected or targeted in the incident, each with name and description of observable state/damage.
- timeline should be an ordered chronological list of observable events, each with start_seconds (float offset from video start), optional end_seconds (float or null), and description.
- uncertainties should list any ambiguities or aspects that cannot be determined confidently (do not invent unconfirmed details).
- location is the camera/location name if mentioned or visible, else empty string.

Use exactly this shape:
{
  "title": "short factual title",
  "incident_type": "road accident | burglary | explosion | fighting | animal",
  "severity": 1,
  "severity_reason": "why this severity was selected",
  "confidence": 0.0,
  "incident_start": null,
  "incident_end": null,
  "incident_start_confirmed": false,
  "duration_seconds": null,
  "description": "1-3 sentence plain-language executive summary",
  "timeline": [{"start_seconds": 0.0, "end_seconds": 1.0, "description": "observable event"}],
  "persons": [{"description": "short physical description", "actions": "specific actions observed"}],
  "instruments": [{"name": "object name", "description": "observable use", "threat_level": null}],
  "assets": [{"name": "asset name", "description": "observable state"}],
  "uncertainties": ["anything that cannot be determined confidently"],
  "location": "camera or setting description if visible, else empty string"
}`;
