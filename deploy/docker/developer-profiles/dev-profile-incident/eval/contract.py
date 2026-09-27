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

"""Shared incident contract (``dev-profile-incident/contracts/``) for Python callers.

The JSON Schema file is the single source of truth. This module loads it, builds
the ``response_format`` payload sent to the model, and validates a response
strictly: ``json.loads`` of the raw content, JSON Schema validation, then the
cross-field rules the schema cannot express. Derived fields (``incident.duration``)
are computed here, not requested from the model. There is no fence stripping, brace
extraction, alias mapping or default filling - a response either conforms or
raises ``ContractError``. See ``.docs/prompt-contract-plan.md``.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
SCHEMA_PATH = CONTRACTS_DIR / "incident_report.schema.json"
EXTRACTION_PROMPT_PATH = CONTRACTS_DIR / "incident_extraction_prompt.md"
REPORT_PROMPT_PATH = CONTRACTS_DIR / "report_generation_prompt.md"
VERSION_PATH = CONTRACTS_DIR / "VERSION"
P1_REQUEST_PATH = CONTRACTS_DIR / "p1_request.json"
RP1_REQUEST_PATH = CONTRACTS_DIR / "rp1_request.json"

# Keys describing the schema document itself; stripped from what is sent to the
# model because some OpenAI-compatible servers reject them inside response_format.
_DOCUMENT_ONLY_KEYS = ("$schema", "$id")


class ContractError(ValueError):
    """A model response does not conform to the incident contract."""


@cache
def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text())


@cache
def contract_version() -> str:
    return VERSION_PATH.read_text().strip()


@cache
def extraction_prompt() -> str:
    return EXTRACTION_PROMPT_PATH.read_text()


@cache
def report_prompt_template() -> str:
    return REPORT_PROMPT_PATH.read_text()


def p1_request() -> dict[str, Any]:
    """Fixed P1 request settings shared by every consumer (temperature, max_tokens, media_io_kwargs)."""
    return json.loads(P1_REQUEST_PATH.read_text())


def rp1_request() -> dict[str, Any]:
    """Fixed RP1 request: ``model`` plus its inference settings, shared by every consumer."""
    return json.loads(RP1_REQUEST_PATH.read_text())


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema())


def response_format() -> dict[str, Any]:
    """OpenAI-compatible ``response_format`` enforcing the contract (strict mode)."""
    schema = {k: v for k, v in load_schema().items() if k not in _DOCUMENT_ONLY_KEYS}
    return {
        "type": "json_schema",
        "json_schema": {"name": "incident_report", "schema": schema, "strict": True},
    }


def cross_field_errors(report: dict[str, Any]) -> list[str]:
    """Rules JSON Schema cannot express. Assumes ``report`` already passed the schema."""
    errors: list[str] = []
    incident = report["incident"]
    start, end = incident["start_timestamp"], incident["end_timestamp"]
    if end < start:
        errors.append(f"end_timestamp {end} is before start_timestamp {start}")

    for prefix, key, items in (
        ("E", "entity_id", report["entities"]),
        ("I", "instrument_id", report["instruments"]),
        ("A", "asset_id", report["assets"]),
    ):
        expected = [f"{prefix}{n}" for n in range(1, len(items) + 1)]
        actual = [item[key] for item in items]
        if actual != expected:
            errors.append(f"{key} values {actual} are not sequential {expected}")

    entity_ids = {e["entity_id"] for e in report["entities"]}
    for instrument in report["instruments"]:
        holder = instrument["entity_id"]
        if holder is not None and holder not in entity_ids:
            errors.append(f"{instrument['instrument_id']} references unknown entity_id {holder}")

    previous_start = None
    for index, event in enumerate(report["timeline"]):
        event_start, event_end = event["start_seconds"], event["end_seconds"]
        if not start <= event_start <= end:
            errors.append(f"timeline[{index}].start_seconds {event_start} is outside [{start}, {end}]")
        if event_end is not None and not event_start <= event_end <= end:
            errors.append(f"timeline[{index}].end_seconds {event_end} is outside [{event_start}, {end}]")
        if previous_start is not None and event_start < previous_start:
            errors.append(f"timeline[{index}] is not in chronological order")
        previous_start = event_start
    return errors


def validate_report(report: Any) -> dict[str, Any]:
    """Validate an already-decoded report; raise ``ContractError`` listing every violation."""
    schema_errors = sorted(_validator().iter_errors(report), key=lambda e: list(e.absolute_path))
    if schema_errors:
        details = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in schema_errors)
        raise ContractError(f"schema violation: {details}")
    errors = cross_field_errors(report)
    if errors:
        raise ContractError(f"cross-field violation: {'; '.join(errors)}")
    return report


def with_derived_fields(report: dict[str, Any]) -> dict[str, Any]:
    """Add fields computed by code, never requested from the model (``incident.duration``)."""
    incident = report["incident"]
    return {**report, "incident": {**incident, "duration": incident["end_timestamp"] - incident["start_timestamp"]}}


def parse_report(content: str | None) -> dict[str, Any]:
    """Strictly decode and validate a model's message content, then add derived fields."""
    if not content:
        raise ContractError("empty response content")
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ContractError(f"content is not a single JSON document: {exc}") from exc
    return with_derived_fields(validate_report(decoded))
