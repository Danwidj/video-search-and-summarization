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

"""Structured incident-report schema produced by the ``/analyze`` pipeline.

Mirrors ``IncidentReport`` in
``deploy/docker/developer-profiles/dev-profile-incident/incident-console/incident_report.py``
and aligns with ``incident-console-v2``'s ``incidentAnalysisSchema`` field-for-field,
since callers parse this tool's output directly. Field names here are the
extraction-facing shape (what an LLM fills in via ``with_structured_output``);
``incident_db.py``'s ``insert_incident`` uses a different, DB-column-facing set of
names (``type``/``severity_level``/``confidence_score``/``start_timestamp``/
``end_timestamp``/``duration``) per ``db.py``'s module docstring, and the
incident_report_gen tool is responsible for that translation.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import Field

# Controlled incident taxonomy - keep in sync with the console's copy in
# incident_report.py and with fixtures/data's seed CSV.
INCIDENT_TYPES: list[str] = [
    "road accident",
    "burglary",
    "explosion",
    "fighting",
    "animal",
]


class Person(BaseModel):
    """A key person identified in an incident. Empty list is valid."""

    description: str = ""
    actions: str = ""


class TimelineItem(BaseModel):
    """A distinct chronological event within the incident."""

    start_seconds: float = 0.0
    end_seconds: float | None = None
    description: str = ""


class Instrument(BaseModel):
    """An object, tool, or weapon observed in the incident."""

    name: str = ""
    description: str = ""
    threat_level: int | None = Field(default=None, ge=1, le=5)


class Asset(BaseModel):
    """A property, structure, vehicle, or resource observed in the incident."""

    name: str = ""
    description: str = ""


class IncidentReport(BaseModel):
    """Structured incident report extracted from a generated video report."""

    title: str = ""
    incident_type: str = INCIDENT_TYPES[0]
    severity: int = Field(default=1, ge=1, le=5)
    severity_reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    incident_start: str = "0:00"
    incident_end: str = "0:00"
    incident_start_confirmed: bool = False
    duration_seconds: int | None = None
    description: str = ""
    persons: list[Person] = Field(default_factory=list)
    instruments: list[Instrument] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    location: str = ""
