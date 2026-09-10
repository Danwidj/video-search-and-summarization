# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""``IncidentReport`` schema plus pure helper logic shared across the app.

This mirrors the ``IncidentReport`` Pydantic schema the plan puts server-side in
``services/agent/src/vss_agents/data_models/incident_report.py`` (out of scope
for this PR). The console keeps its own copy so it can parse AI-trigger
responses and render the report form without importing the agent package.
"""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

# Taxonomy for the Supabase 8-mock dataset: warehouse-safety / operations /
# traffic / pedestrian / structural footage the captain uploaded to R2.
INCIDENT_TYPES: list[str] = [
    "warehouse safety",
    "equipment",
    "pedestrian",
    "traffic",
    "structural",
    "other",
]

REPORT_STATUSES: list[str] = ["unreviewed", "verified"]


class Person(BaseModel):
    """A key person identified in an incident. Empty list is valid."""

    description: str = ""
    actions: str = ""


class IncidentReport(BaseModel):
    """Structured incident report produced by the analyze pipeline."""

    incident_type: str = "other"
    severity: int = Field(default=1, ge=1, le=5)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    incident_start: str = "0:00"
    incident_end: str = "0:00"
    incident_start_confirmed: bool = False
    description: str = ""
    persons: list[Person] = Field(default_factory=list)
    location: str = ""


# --------------------------------------------------------------------------- #
# Timestamp helpers
# --------------------------------------------------------------------------- #
def timestamp_to_seconds(value: str | int | float | None) -> int:
    """Parse ``MM:SS`` / ``HH:MM:SS`` / bare seconds. Fallback to 0 on anything odd."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if not text:
        return 0
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        try:
            return max(0, int(float(text)))
        except ValueError:
            return 0
    if len(parts) == 1:
        return max(0, parts[0])
    if len(parts) == 2:
        return max(0, parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return max(0, parts[0] * 3600 + parts[1] * 60 + parts[2])
    return 0


def seconds_to_timestamp(seconds: int | float | None) -> str:
    total = max(0, int(seconds or 0))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def playback_start_seconds(report: dict) -> int:
    """Where ``st.video`` should seek to. 0 when the start is unconfirmed."""
    if not report.get("incident_start_confirmed"):
        return 0
    return timestamp_to_seconds(report.get("incident_start"))


# --------------------------------------------------------------------------- #
# Severity / notification thresholds (plan defaults, not spec-sourced)
# --------------------------------------------------------------------------- #
def severity_triggers_notification(severity: int | None, threshold: int) -> bool:
    try:
        return int(severity) >= int(threshold)
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Notification grouping
# --------------------------------------------------------------------------- #
def group_notifications(rows: Sequence[dict], window_seconds: int = 300) -> list[list[dict]]:
    """Bucket notifications whose ``created_at`` epoch seconds fall in the same window.

    ``rows`` must each carry a numeric ``created_at_epoch``. Rows without one are
    each returned as their own group so nothing is silently dropped.
    """
    groups: list[list[dict]] = []
    current: list[dict] = []
    anchor: float | None = None
    # Timestamp-less rows sort to the end so they never split a real window.
    ordered = sorted(
        rows,
        key=lambda r: (r.get("created_at_epoch") is None, r.get("created_at_epoch") or 0),
    )
    for row in ordered:
        epoch = row.get("created_at_epoch")
        if epoch is None:
            if current:
                groups.append(current)
                current = []
            groups.append([row])
            anchor = None
            continue
        if anchor is None or epoch - anchor > window_seconds:
            if current:
                groups.append(current)
            current = [row]
            anchor = epoch
        else:
            current.append(row)
    if current:
        groups.append(current)
    return groups


# --------------------------------------------------------------------------- #
# Dashboard insights (templated over aggregate rows - no ML)
# --------------------------------------------------------------------------- #
def build_insights(reports: Sequence[dict]) -> list[str]:
    """Templated natural-language insights over a set of report dicts."""
    reports = list(reports)
    if not reports:
        return ["No verified incident reports match the current filters."]

    insights: list[str] = []
    total = len(reports)
    insights.append(f"{total} verified incident report{'s' if total != 1 else ''} in view.")

    by_type: dict[str, int] = {}
    by_location: dict[str, int] = {}
    high_sev = 0
    for r in reports:
        by_type[r.get("incident_type") or "other"] = by_type.get(r.get("incident_type") or "other", 0) + 1
        loc = (r.get("location") or "").strip() or "unknown location"
        by_location[loc] = by_location.get(loc, 0) + 1
        try:
            if int(r.get("severity") or 0) >= 4:
                high_sev += 1
        except (TypeError, ValueError):
            pass

    top_type, top_type_n = max(by_type.items(), key=lambda kv: kv[1])
    insights.append(f'Most common incident type is "{top_type}" ({top_type_n} of {total}, {top_type_n / total:.0%}).')

    top_loc, top_loc_n = max(by_location.items(), key=lambda kv: kv[1])
    if top_loc_n > 1:
        insights.append(f'"{top_loc}" is the most frequent location with {top_loc_n} reports.')

    if high_sev:
        insights.append(
            f"{high_sev} report{'s' if high_sev != 1 else ''} at severity 4-5 ({high_sev / total:.0%} of view)."
        )
    return insights


# --------------------------------------------------------------------------- #
# Parsing AI-trigger / chat-completion output into an IncidentReport
# --------------------------------------------------------------------------- #
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_OBJECT = re.compile(r"(\{[\s\S]*\"incident_type\"[\s\S]*\})")


def _coerce_persons(raw: object) -> list[Person]:
    persons: list[Person] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                persons.append(
                    Person(
                        description=str(item.get("description", "")),
                        actions=str(item.get("actions", "")),
                    )
                )
            elif isinstance(item, str):
                persons.append(Person(description=item))
    return persons


def incident_report_from_dict(data: dict) -> IncidentReport:
    """Build an ``IncidentReport`` from a loosely-typed dict, clamping values."""
    report = IncidentReport()
    if not isinstance(data, dict):
        return report

    itype = str(data.get("incident_type", "")).strip().lower()
    report.incident_type = itype if itype in INCIDENT_TYPES else "other"

    with contextlib.suppress(KeyError, TypeError, ValueError):
        report.severity = max(1, min(5, int(round(float(data["severity"])))))

    with contextlib.suppress(KeyError, TypeError, ValueError):
        conf = float(data["confidence"])
        report.confidence = max(0.0, min(1.0, conf / 100.0 if conf > 1.0 else conf))

    if data.get("incident_start") is not None:
        report.incident_start = seconds_to_timestamp(timestamp_to_seconds(data["incident_start"]))
    if data.get("incident_end") is not None:
        report.incident_end = seconds_to_timestamp(timestamp_to_seconds(data["incident_end"]))
    report.incident_start_confirmed = bool(data.get("incident_start_confirmed", False))
    report.description = str(data.get("description", "") or "")
    report.location = str(data.get("location", "") or "")
    report.persons = _coerce_persons(data.get("persons"))
    return report


def parse_incident_report(content: str) -> IncidentReport:
    """Extract an ``IncidentReport`` from a chat-completion ``content`` string.

    Tries a fenced JSON block, then a bare ``{...}`` object, then falls back to
    an empty report carrying the raw text as the description.
    """
    if not content:
        return IncidentReport()

    for pattern in (_JSON_BLOCK, _BARE_OBJECT):
        match = pattern.search(content)
        if not match:
            continue
        try:
            return incident_report_from_dict(json.loads(match.group(1)))
        except (json.JSONDecodeError, TypeError):
            continue

    try:
        return incident_report_from_dict(json.loads(content))
    except (json.JSONDecodeError, TypeError):
        return IncidentReport(description=content.strip())


def extract_message_content(completion: dict) -> str:
    """Pull ``choices[0].message.content`` out of an OpenAI-shaped response."""
    try:
        choice = completion["choices"][0]
    except (KeyError, IndexError, TypeError):
        return ""
    message = choice.get("message") or {}
    return message.get("content") or message.get("reasoning_content") or ""


def canned_incident_report(prompt: str = "") -> IncidentReport:
    """Deterministic sample report - used by the mock server and tests."""
    text = (prompt or "").lower()
    report = IncidentReport(
        incident_type="warehouse safety",
        severity=2,
        confidence=0.78,
        incident_start="0:07",
        incident_end="0:29",
        incident_start_confirmed=True,
        description=(
            "a warehouse operator lifts a carton from a low pallet with a rounded "
            "back and no knee bend, close to occupied racking. no other people in frame."
        ),
        persons=[Person(description="operator in a hi-vis vest", actions="manual lift with poor back posture")],
        location="Warehouse Floor Camera",
    )
    if any(k in text for k in ("ladder", "fall", "height", "top rung")):
        report.incident_type = "warehouse safety"
        report.severity = 4
        report.confidence = 0.55
    elif any(k in text for k in ("forklift", "conveyor", "pallet jack", "equipment")):
        report.incident_type = "equipment"
        report.severity = 3
        report.confidence = 0.86
    elif any(k in text for k in ("pedestrian", "cross", "jaywalk")):
        report.incident_type = "pedestrian"
        report.severity = 3
        report.confidence = 0.66
    elif any(k in text for k in ("bridge", "crack", "structural", "rebar")):
        report.incident_type = "structural"
        report.severity = 4
        report.confidence = 0.9
    return report


def to_completion_payload(report: IncidentReport, model: str = "mock-incident-llm") -> dict:
    """Wrap an ``IncidentReport`` in an OpenAI chat-completion response shape."""
    body = json.dumps(report.model_dump(), indent=2)
    return {
        "id": "chatcmpl-mock-incident",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": body},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def dedupe_types(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    return seen
