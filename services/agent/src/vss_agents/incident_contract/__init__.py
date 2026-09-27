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

"""The shared incident contract (``dev-profile-incident/contracts/``) for the agent.

The files next to this module are a vendored copy of the profile's ``contracts/``
directory (the agent is deployed from ``services/agent``); a unit test fails when
the two copies differ. The JSON Schema file is what the model is sent as
``response_format``. Responses are validated strictly with the Pydantic models below
(``strict=True``, ``extra="forbid"``), which mirror that schema - another unit test
checks the two agree - then with the cross-field rules the schema cannot express.

There is no fence stripping, brace extraction, alias mapping, coercion or repair: a
response either conforms or raises :class:`IncidentExtractionError`. See
``.docs/prompt-contract-plan.md`` in the incident profile.
"""

from __future__ import annotations

from functools import cache
import json
from pathlib import Path
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError

CONTRACT_DIR = Path(__file__).resolve().parent

IncidentType = Literal["road accident", "burglary", "explosion", "assault", "animal attack"]
EntityType = Literal["human", "animal", "unknown"]

_STRICT = ConfigDict(strict=True, extra="forbid")


class IncidentExtractionError(ValueError):
    """A model response does not conform to the incident contract (HTTP 422 on ``/analyze``)."""


class ContractIncident(BaseModel):
    """``incident`` as the model returns it; ``duration`` is derived afterwards, never requested."""

    model_config = _STRICT

    type: IncidentType
    title: str
    start_timestamp: int = Field(ge=0)
    end_timestamp: int = Field(ge=0)
    description: str
    # Strict int with bounds rather than Literal[1..5]: Literal compares by equality, so it would
    # accept true and 3.0, which the JSON Schema enum rejects.
    severity_level: int = Field(ge=1, le=5)
    severity_reason: str
    confidence_score: float | None = Field(ge=0, le=1)
    location: str | None


class ContractEntity(BaseModel):
    model_config = _STRICT

    entity_id: str
    type: EntityType
    description: str


class ContractInstrument(BaseModel):
    model_config = _STRICT

    instrument_id: str
    entity_id: str | None
    name: str
    description: str
    threat_level: int = Field(ge=1, le=5)


class ContractAsset(BaseModel):
    model_config = _STRICT

    asset_id: str
    name: str
    description: str


class ContractTimelineEvent(BaseModel):
    model_config = _STRICT

    start_seconds: int = Field(ge=0)
    end_seconds: int | None = Field(ge=0)
    description: str


class ContractReport(BaseModel):
    """The P1 output exactly as the contract schema defines it (no derived fields)."""

    model_config = _STRICT

    incident: ContractIncident
    entities: list[ContractEntity]
    instruments: list[ContractInstrument]
    assets: list[ContractAsset]
    timeline: list[ContractTimelineEvent]
    uncertainties: list[str]


def _read(name: str) -> str:
    return (CONTRACT_DIR / name).read_text(encoding="utf-8")


def _read_json(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_read(name))
    return data


@cache
def load_schema() -> dict[str, Any]:
    return _read_json("incident_report.schema.json")


@cache
def contract_version() -> str:
    return _read("VERSION").strip()


@cache
def extraction_prompt() -> str:
    return _read("incident_extraction_prompt.md")


@cache
def report_prompt_template() -> str:
    return _read("report_generation_prompt.md")


def p1_request() -> dict[str, Any]:
    """Fixed P1 request settings shared with eval and the console (temperature, max_tokens, media_io_kwargs)."""
    return _read_json("p1_request.json")


def rp1_request() -> dict[str, Any]:
    """Fixed RP1 request: ``model`` plus its inference settings, shared with eval and the console."""
    return _read_json("rp1_request.json")


def response_format() -> dict[str, Any]:
    """OpenAI-compatible ``response_format`` enforcing the contract schema file (strict mode)."""
    schema = {key: value for key, value in load_schema().items() if key not in ("$schema", "$id")}
    return {"type": "json_schema", "json_schema": {"name": "incident_report", "schema": schema, "strict": True}}


def cross_field_errors(report: ContractReport) -> list[str]:
    """Rules JSON Schema cannot express (same rules as eval/contract.py and the console)."""
    errors: list[str] = []
    start, end = report.incident.start_timestamp, report.incident.end_timestamp
    if end < start:
        errors.append(f"end_timestamp {end} is before start_timestamp {start}")

    for prefix, key, ids in (
        ("E", "entity_id", [entity.entity_id for entity in report.entities]),
        ("I", "instrument_id", [item.instrument_id for item in report.instruments]),
        ("A", "asset_id", [item.asset_id for item in report.assets]),
    ):
        expected = [f"{prefix}{n}" for n in range(1, len(ids) + 1)]
        if ids != expected:
            errors.append(f"{key} values {ids} are not sequential {expected}")

    entity_ids = {entity.entity_id for entity in report.entities}
    for instrument in report.instruments:
        if instrument.entity_id is not None and instrument.entity_id not in entity_ids:
            errors.append(f"{instrument.instrument_id} references unknown entity_id {instrument.entity_id}")

    previous_start: int | None = None
    for index, event in enumerate(report.timeline):
        if not start <= event.start_seconds <= end:
            errors.append(f"timeline[{index}].start_seconds {event.start_seconds} is outside [{start}, {end}]")
        if event.end_seconds is not None and not event.start_seconds <= event.end_seconds <= end:
            errors.append(
                f"timeline[{index}].end_seconds {event.end_seconds} is outside [{event.start_seconds}, {end}]"
            )
        if previous_start is not None and event.start_seconds < previous_start:
            errors.append(f"timeline[{index}] is not in chronological order")
        previous_start = event.start_seconds
    return errors


def with_derived_fields(report: ContractReport) -> dict[str, Any]:
    """The validated report as a plain dict plus fields computed by code (``incident.duration``)."""
    data = report.model_dump(mode="json")
    data["incident"]["duration"] = report.incident.end_timestamp - report.incident.start_timestamp
    return data


def validate_report(value: Any) -> dict[str, Any]:
    """Validate an already-decoded model output; raise :class:`IncidentExtractionError` listing every violation."""
    try:
        report = ContractReport.model_validate(value)
    except ValidationError as exc:
        details = "; ".join(
            f"{'/'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}" for error in exc.errors()
        )
        raise IncidentExtractionError(f"schema violation: {details}") from exc
    errors = cross_field_errors(report)
    if errors:
        raise IncidentExtractionError(f"cross-field violation: {'; '.join(errors)}")
    return with_derived_fields(report)


def parse_report(content: str | None) -> dict[str, Any]:
    """Strictly decode and validate a model's message content, then add derived fields."""
    if not content:
        raise IncidentExtractionError("empty response content")
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as exc:
        raise IncidentExtractionError(f"content is not a single JSON document: {exc}") from exc
    return validate_report(decoded)


def report_prompt(report: dict[str, Any]) -> str:
    """The RP1 prompt for a validated (derived) report."""
    return report_prompt_template().format(structured_incident_json=json.dumps(report, indent=2))
