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

"""The vendored incident contract: parity with the profile copy and with the JSON Schema, strict parsing."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from vss_agents import incident_contract
from vss_agents.incident_contract import ContractReport
from vss_agents.incident_contract import IncidentExtractionError

PROFILE_CONTRACTS = (
    Path(__file__).resolve().parents[5] / "deploy/docker/developer-profiles/dev-profile-incident/contracts"
)
VENDORED_FILES = [
    "incident_report.schema.json",
    "incident_extraction_prompt.md",
    "report_generation_prompt.md",
    "VERSION",
    "p1_request.json",
    "rp1_request.json",
]

VALID = {
    "incident": {
        "type": "assault",
        "title": "Person strikes another person with a bottle",
        "start_timestamp": 3,
        "end_timestamp": 11,
        "description": "E1 approaches E2 and strikes E2 with a bottle.",
        "severity_level": 3,
        "severity_reason": "Repeated strikes with an improvised weapon.",
        "confidence_score": None,
        "location": "shop interior",
    },
    "entities": [
        {"entity_id": "E1", "type": "human", "description": "Attacker."},
        {"entity_id": "E2", "type": "human", "description": "Victim."},
    ],
    "instruments": [
        {"instrument_id": "I1", "entity_id": "E1", "name": "bottle", "description": "Glass.", "threat_level": 3}
    ],
    "assets": [{"asset_id": "A1", "name": "counter", "description": "Shop counter."}],
    "timeline": [
        {"start_seconds": 3, "end_seconds": 5, "description": "E1 approaches E2."},
        {"start_seconds": 5, "end_seconds": 11, "description": "E1 strikes E2 with I1."},
    ],
    "uncertainties": ["It is unclear whether E2 was injured."],
}


def _valid() -> dict:
    return copy.deepcopy(VALID)


@pytest.mark.parametrize("name", VENDORED_FILES)
def test_vendored_file_matches_profile_contracts(name):
    assert (incident_contract.CONTRACT_DIR / name).read_bytes() == (PROFILE_CONTRACTS / name).read_bytes(), (
        f"services/agent/src/vss_agents/incident_contract/{name} differs from the profile contracts/ copy; "
        "copy the profile file over it"
    )


def _objects(schema: dict, model: type) -> list[tuple[dict, type]]:
    """Pair every object in the JSON Schema with the Pydantic model that mirrors it."""
    pairs = [(schema, model)]
    for name, field in model.model_fields.items():
        prop = schema["properties"][name]
        annotation = field.annotation
        if prop.get("type") == "object":
            pairs += _objects(prop, annotation)
        elif prop.get("type") == "array" and prop["items"].get("type") == "object":
            pairs += _objects(prop["items"], annotation.__args__[0])
    return pairs


def test_pydantic_models_mirror_the_schema():
    pairs = _objects(incident_contract.load_schema(), ContractReport)
    assert len(pairs) == 6
    for schema_object, model in pairs:
        assert set(model.model_fields) == set(schema_object["properties"]), model.__name__
        assert set(schema_object["required"]) == set(schema_object["properties"])
        assert schema_object["additionalProperties"] is False
        assert model.model_config.get("extra") == "forbid" and model.model_config.get("strict") is True
    incident = incident_contract.load_schema()["properties"]["incident"]["properties"]
    assert incident["type"]["enum"] == ["road accident", "burglary", "explosion", "assault", "animal attack"]
    assert "duration" not in incident


def test_valid_report_parses_and_duration_is_derived():
    report = incident_contract.parse_report(json.dumps(VALID))
    assert report["incident"]["duration"] == 8
    assert {k: v for k, v in report["incident"].items() if k != "duration"} == VALID["incident"]


@pytest.mark.parametrize(
    "content",
    [None, "", "```json\n{}\n```", 'Here: {"incident": {}}', "<think>x</think>" + json.dumps(VALID)],
)
def test_no_extraction_heuristics(content):
    with pytest.raises(IncidentExtractionError):
        incident_contract.parse_report(content)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["incident"].update(type="fighting"), "schema violation"),
        (lambda r: r["incident"].update(duration=8), "schema violation"),
        (lambda r: r["incident"].update(severity_level=True), "schema violation"),
        (lambda r: r["incident"].update(severity_level=3.0), "schema violation"),
        (lambda r: r["incident"].update(severity_level="3"), "schema violation"),
        (lambda r: r["incident"].update(confidence_score=1.5), "schema violation"),
        (lambda r: r["incident"].pop("title"), "schema violation"),
        (lambda r: r.update(persons=[]), "schema violation"),
        (lambda r: r["entities"][0].update(type="person"), "schema violation"),
        (lambda r: r["instruments"][0].update(threat_level=0), "schema violation"),
        (lambda r: r["incident"].update(end_timestamp=2), "before start_timestamp"),
        (lambda r: r["entities"][1].update(entity_id="E3"), "not sequential"),
        (lambda r: r["instruments"][0].update(entity_id="E9"), "unknown entity_id"),
        (lambda r: r["timeline"][0].update(start_seconds=0), "outside"),
        (lambda r: r["timeline"].reverse(), "chronological"),
    ],
)
def test_contract_violations(mutate, message):
    report = _valid()
    mutate(report)
    with pytest.raises(IncidentExtractionError, match=message):
        incident_contract.validate_report(report)


def test_int_confidence_and_nulls_are_valid():
    report = _valid()
    report["incident"]["confidence_score"] = 1
    report["incident"]["location"] = None
    report["instruments"][0]["entity_id"] = None
    assert incident_contract.validate_report(report)["incident"]["confidence_score"] == 1


def test_response_format_is_strict_and_uses_the_schema_file():
    fmt = incident_contract.response_format()
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert "$schema" not in fmt["json_schema"]["schema"] and "$id" not in fmt["json_schema"]["schema"]
    assert fmt["json_schema"]["schema"]["properties"] == incident_contract.load_schema()["properties"]


def test_report_prompt_embeds_the_derived_report():
    report = incident_contract.parse_report(json.dumps(VALID))
    prompt = incident_contract.report_prompt(report)
    assert '"duration": 8' in prompt and '"type": "assault"' in prompt
