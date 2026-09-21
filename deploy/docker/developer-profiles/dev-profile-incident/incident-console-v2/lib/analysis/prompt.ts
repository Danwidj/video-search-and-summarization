// SPDX-License-Identifier: Apache-2.0

export const INCIDENT_PROMPT_VERSION = 'incident-v2-1';

export const INCIDENT_ANALYSIS_PROMPT = `Analyze this surveillance video and return one JSON object only.
Do not use Markdown fences and do not include commentary before or after the JSON.
Base findings only on visible evidence. Put ambiguity in uncertainties rather than inventing details.
Timestamps must be offsets from the beginning of the video.

Use exactly this shape:
{
  "title": "short factual title",
  "incidentType": "road accident | burglary | explosion | fighting | animal | other",
  "summary": "plain-language executive summary",
  "startTimestamp": "HH:MM:SS or null",
  "endTimestamp": "HH:MM:SS or null",
  "durationSeconds": 0,
  "severityLevel": 1,
  "severityReason": "why this severity was selected",
  "confidenceScore": 0.0,
  "timeline": [{"startSeconds": 0, "endSeconds": 1, "description": "observable event"}],
  "entities": [{"type": "human | animal | unknown", "description": "observable description"}],
  "instruments": [{"name": "object name", "description": "observable use", "threatLevel": null}],
  "assets": [{"name": "asset name", "description": "observable state"}],
  "uncertainties": ["anything that cannot be determined confidently"]
}`;
