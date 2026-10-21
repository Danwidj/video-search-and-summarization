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
import importlib.util
import json
from pathlib import Path

import pytest

from vss_agents import incident_contract
from vss_agents.incident_contract import ContractReport
from vss_agents.incident_contract import IncidentExtractionError

PROFILE_CONTRACTS = (
    Path(__file__).resolve().parents[5] / "deploy/docker/developer-profiles/dev-profile-incident/contracts"
)

_sync_spec = importlib.util.spec_from_file_location("contract_sync", PROFILE_CONTRACTS / "sync.py")
if _sync_spec is None or _sync_spec.loader is None:
    raise ImportError(f"Could not load sync script from {PROFILE_CONTRACTS / 'sync.py'}")
_sync_module = importlib.util.module_from_spec(_sync_spec)
_sync_spec.loader.exec_module(_sync_module)
VENDORED_FILES = _sync_module.VENDORED_FILES
check_file = _sync_module.check_file
check_drift = _sync_module.check_drift

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
        {"entity_id": "E1", "type": "human", "description": "Attacker.", "timestamp_seconds": 3, "label": "attacker"},
        {"entity_id": "E2", "type": "human", "description": "Victim.", "timestamp_seconds": 3, "label": "victim"},
    ],
    "instruments": [
        {
            "instrument_id": "I1",
            "entity_id": "E1",
            "name": "bottle",
            "description": "Glass.",
            "threat_level": 3,
            "timestamp_seconds": 5,
            "label": "bottle",
        }
    ],
    "assets": [
        {
            "asset_id": "A1",
            "name": "counter",
            "description": "Shop counter.",
            "timestamp_seconds": 3,
            "label": "counter",
        }
    ],
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
    assert check_file(name, PROFILE_CONTRACTS, incident_contract.CONTRACT_DIR), (
        f"services/agent/src/vss_agents/incident_contract/{name} differs from the profile contracts/ copy; "
        "run deploy/docker/developer-profiles/dev-profile-incident/contracts/sync.py to update it"
    )


def test_no_vendored_contract_drift():
    differing = check_drift(PROFILE_CONTRACTS, incident_contract.CONTRACT_DIR)
    assert not differing, (
        f"Contract files differ: {differing}; "
        "run deploy/docker/developer-profiles/dev-profile-incident/contracts/sync.py to update it"
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
    ],
)
def test_contract_violations(mutate, message):
    report = _valid()
    mutate(report)
    with pytest.raises(IncidentExtractionError, match=message):
        incident_contract.validate_report(report)


ID_CODES = {"ID_NOT_SEQUENTIAL_ENTITY", "ID_NOT_SEQUENTIAL_INSTRUMENT", "ID_NOT_SEQUENTIAL_ASSET"}
POLICY_FIXTURES = sorted(
    path
    for path in (PROFILE_CONTRACTS / "fixtures" / "policy").glob("*.json")
    if not ID_CODES & set(json.loads(path.read_text(encoding="utf-8"))["expected"]["core_codes"])
)


@pytest.mark.parametrize("path", POLICY_FIXTURES, ids=lambda path: path.stem)
def test_core_scored_v1_matches_the_shared_policy_fixtures(path):
    """Accepted iff core-scored-v1 finds no core violation."""
    fixture = json.loads(path.read_text(encoding="utf-8"))
    accepted = fixture["expected"]["core_ok"]
    duration = fixture.get("video_duration_seconds")
    if accepted:
        report = incident_contract.parse_report(fixture["content"], video_duration_seconds=duration)
        original = json.loads(fixture["content"])
        assert report["timeline"] == original["timeline"], "enrichment violations are recorded, never repaired"
    else:
        with pytest.raises(IncidentExtractionError):
            incident_contract.parse_report(fixture["content"], video_duration_seconds=duration)


def test_id_only_violation_is_repaired_by_id_normalization():
    """The console's recorded malformed-ID response, repaired as its gateway-mode test expects."""
    fixture = json.loads(
        (
            PROFILE_CONTRACTS.parent
            / "incident-console-v2/tests/fixtures/contract-failures/nemotron-3-omni-malformed-ids.json"
        ).read_text(encoding="utf-8")
    )
    report = incident_contract.parse_report(fixture["rawContent"])
    assert [entity["entity_id"] for entity in report["entities"]] == ["E1", "E2"]
    assert [(i["instrument_id"], i["entity_id"], i["name"]) for i in report["instruments"]] == [
        ("I1", "E1", "bag"),
        ("I2", None, "white van"),
    ]


def test_renamed_ids_remap_instrument_holders():
    report = _valid()
    for entity, text in zip(report["entities"], ("Attacker.", "Victim."), strict=True):
        entity["description"] = text
    report["incident"]["description"] = "The attacker strikes the victim with a bottle."
    report["timeline"][1]["description"] = "The attacker strikes the victim."
    report["timeline"][0]["description"] = "The attacker approaches."
    report["uncertainties"] = []
    report["entities"][0]["entity_id"], report["entities"][1]["entity_id"] = "E7", "E5"
    report["instruments"][0]["entity_id"] = "E5"
    repaired = incident_contract.validate_report(report)
    assert [(e["entity_id"], e["description"]) for e in repaired["entities"]] == [
        ("E1", "Attacker."),
        ("E2", "Victim."),
    ]
    assert repaired["instruments"][0]["entity_id"] == "E2"


def test_id_repair_is_refused_when_free_text_mentions_a_renamed_id():
    report = _valid()
    report["entities"][1]["entity_id"] = "E3"
    with pytest.raises(IncidentExtractionError, match="not sequential"):
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


def test_p1_request_matches_inference_json():
    p1 = incident_contract.p1_request()
    assert p1["temperature"] == 0.0
    assert p1["max_tokens"] == 16384
    assert p1["media_io_kwargs"] == {"video": {"num_frames": 64}}


def test_video_bounds_violations_and_enrichment_handling():
    report = _valid()
    end = report["incident"]["end_timestamp"]  # 11
    # Beyond video length when duration is known -> rejected
    with pytest.raises(IncidentExtractionError, match="outside the 10 s video"):
        incident_contract.validate_report(report, video_duration_seconds=end - 1)

    # Within video length (whole-second rule) -> accepted
    res_within = incident_contract.validate_report(report, video_duration_seconds=end - 0.5)
    assert res_within["incident"]["end_timestamp"] == end

    # Unknown video length -> not checked, accepted
    res_unknown = incident_contract.validate_report(report, video_duration_seconds=None)
    assert res_unknown["incident"]["end_timestamp"] == end

    # Timeline beyond video is an enrichment violation -> accepted, not fatal
    report["timeline"][1]["start_seconds"] = 15
    report["incident"]["end_timestamp"] = 20
    # Window [3, 20] is beyond 18 s video -> core rejection
    with pytest.raises(IncidentExtractionError, match="outside the 18 s video"):
        incident_contract.validate_report(report, video_duration_seconds=18)
    # Window [3, 20] is within 25 s video, timeline event start 15 is within -> accepted
    res_enrich = incident_contract.validate_report(report, video_duration_seconds=25)
    assert res_enrich["timeline"][1]["start_seconds"] == 15


def test_id_normalization_instrument_holder_unknown_ineligible_does_not_crash():
    report = _valid()
    report["instruments"][0]["entity_id"] = "E9"
    with pytest.raises(IncidentExtractionError, match="unknown entity_id E9"):
        incident_contract.validate_report(report)


def test_id_normalization_instrument_holder_remapped():
    report = _valid()
    for entity, text in zip(report["entities"], ("Attacker.", "Victim."), strict=True):
        entity["description"] = text
    report["incident"]["description"] = "The attacker strikes the victim with a bottle."
    report["timeline"][1]["description"] = "The attacker strikes the victim."
    report["timeline"][0]["description"] = "The attacker approaches."
    report["uncertainties"] = []
    # Both entity and instrument holder use malformed "e1"
    report["entities"][0]["entity_id"] = "e1"
    report["instruments"][0]["entity_id"] = "e1"
    repaired = incident_contract.validate_report(report)
    assert repaired["entities"][0]["entity_id"] == "E1"
    assert repaired["instruments"][0]["entity_id"] == "E1"


def test_id_normalization_invariance_check_preserves_semantics(monkeypatch):
    report = _valid()
    for entity, text in zip(report["entities"], ("Attacker.", "Victim."), strict=True):
        entity["description"] = text
    report["incident"]["description"] = "The attacker strikes the victim with a bottle."
    report["timeline"][1]["description"] = "The attacker strikes the victim."
    report["timeline"][0]["description"] = "The attacker approaches."
    report["uncertainties"] = []
    report["entities"][0]["entity_id"] = "e1"
    report["instruments"][0]["entity_id"] = "e1"
    model_report = ContractReport.model_validate(report)
    violations = incident_contract.cross_field_violations(model_report)

    repaired = incident_contract.normalize_ids(model_report, violations)
    assert repaired is not None
    assert [e.entity_id for e in repaired.entities] == ["E1", "E2"]
    assert repaired.instruments[0].entity_id == "E1"
    assert repaired.incident == model_report.incident
    assert repaired.timeline == model_report.timeline
    assert repaired.uncertainties == model_report.uncertainties
    assert repaired.assets == model_report.assets
    assert [(e.type, e.description, e.timestamp_seconds, e.label) for e in repaired.entities] == [
        ("human", "Attacker.", 3, "attacker"),
        ("human", "Victim.", 3, "victim"),
    ]
    assert (
        repaired.instruments[0].name,
        repaired.instruments[0].description,
        repaired.instruments[0].threat_level,
        repaired.instruments[0].timestamp_seconds,
        repaired.instruments[0].label,
    ) == ("bottle", "Glass.", 3, 5, "bottle")

    assert incident_contract._semantic_projection(model_report) == incident_contract._semantic_projection(repaired)

    mutated_holder = repaired.model_copy(deep=True)
    mutated_holder.instruments[0].entity_id = "E2"
    assert incident_contract._semantic_projection(mutated_holder) != incident_contract._semantic_projection(repaired)

    mutated_desc = repaired.model_copy(deep=True)
    mutated_desc.entities[0].description = "Different person."
    assert incident_contract._semantic_projection(mutated_desc) != incident_contract._semantic_projection(repaired)

    orig_proj = incident_contract._semantic_projection
    monkeypatch.setattr(
        incident_contract,
        "_semantic_projection",
        lambda r: orig_proj(r) if r is model_report else orig_proj(r) + "mutation",
    )
    assert incident_contract.normalize_ids(model_report, violations) is None
