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
field-for-field, since the console parses this tool's output directly. Field
names here are the extraction-facing shape (what an LLM fills in via
``with_structured_output``); ``incident_db.py``'s ``insert_incident`` uses a
different, DB-column-facing set of names (``type``/``severity_level``/
``confidence_score``/``start_timestamp``/``end_timestamp``) per
``db.py``'s module docstring, and the incident_report_gen tool is
responsible for that translation.
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


class IncidentReport(BaseModel):
    """Structured incident report extracted from a generated video report."""

    incident_type: str = INCIDENT_TYPES[0]
    severity: int = Field(default=1, ge=1, le=5)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    incident_start: str = "0:00"
    incident_end: str = "0:00"
    incident_start_confirmed: bool = False
    description: str = ""
    persons: list[Person] = Field(default_factory=list)
    location: str = ""
