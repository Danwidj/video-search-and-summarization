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

"""Model-output evidence (entities/instruments/assets), ground truth, and matches."""

from __future__ import annotations

from db import IncidentDB, metadata


def test_evidence_and_gt_tables_are_keyed_correctly():
    id_cols = {
        "entities": {"incident_id", "entity_id", "model_run_id"},
        "instruments": {"incident_id", "instrument_id", "model_run_id"},
        "assets": {"incident_id", "asset_id", "model_run_id"},
        "gt_entities": {"incident_id", "entity_id"},
        "gt_instruments": {"incident_id", "instrument_id"},
        "gt_assets": {"incident_id", "asset_id"},
    }
    for table, pk_cols in id_cols.items():
        cols = {c.name for c in metadata.tables[table].columns}
        assert "image" in cols
        assert pk_cols <= cols
        pk = {c.name for c in metadata.tables[table].primary_key.columns}
        assert pk == pk_cols


def _seed_incident(db: IncidentDB, incident_id="Equip001", model_run_id="MR-1"):
    db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4")
    db.insert_model_run(model_run_id, model_name="incident-vlm", prompt_version="p1")
    db.insert_incident(incident_id, model_run_id, fields={"type": "burglary", "severity_level": 3})
    return incident_id, model_run_id


def test_model_output_evidence_crud_roundtrip(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident(incident_db)

    incident_db.add_incident_entity(incident_id, model_run_id, entity_id="E1", type="human", description="operator")
    incident_db.add_incident_instrument(
        incident_id,
        model_run_id,
        instrument_id="I1",
        entity_id="E1",
        name="forklift",
        description="laden",
        threat_level=3,
    )
    incident_db.add_incident_asset(incident_id, model_run_id, asset_id="A1", name="racking", description="loaded bay")

    entities = incident_db.list_incident_entities(incident_id, model_run_id)
    instruments = incident_db.list_incident_instruments(incident_id, model_run_id)
    assets = incident_db.list_incident_assets(incident_id, model_run_id)
    assert [e["entity_id"] for e in entities] == ["E1"]
    assert entities[0]["type"] == "human"
    assert entities[0]["image"] is None
    assert instruments[0]["threat_level"] == 3
    assert instruments[0]["entity_id"] == "E1"
    assert assets[0]["name"] == "racking"

    # Scoped to (incident_id, model_run_id); another run sees nothing.
    incident_db.insert_model_run("MR-2", model_name="incident-vlm", prompt_version="p1")
    incident_db.insert_incident(incident_id, "MR-2", fields={"type": "burglary", "severity_level": 1})
    assert incident_db.list_incident_entities(incident_id, "MR-2") == []

    incident_db.clear_incident_evidence(incident_id, model_run_id)
    assert incident_db.list_incident_entities(incident_id, model_run_id) == []
    assert incident_db.list_incident_instruments(incident_id, model_run_id) == []
    assert incident_db.list_incident_assets(incident_id, model_run_id) == []


def test_ground_truth_crud_roundtrip(incident_db: IncidentDB):
    incident_db.upsert_video("Burglary002", filepath="normal_videos/Burglary002.mp4")
    incident_db.insert_gt_incident(
        "Burglary002",
        fields={
            "type": "burglary",
            "severity_level": 4,
            "description": "ground truth description",
            "labelled_by": "annotator-1",
        },
    )
    gt = incident_db.get_gt_incident("Burglary002")
    assert gt["severity_level"] == 4
    assert gt["labelled_by"] == "annotator-1"
    assert len(incident_db.list_gt_incidents()) == 1

    incident_db.add_gt_entity("Burglary002", entity_id="E1", type="human", description="masked person")
    incident_db.add_gt_instrument("Burglary002", instrument_id="I1", entity_id="E1", name="crowbar", threat_level=2)
    incident_db.add_gt_asset("Burglary002", asset_id="A1", name="cash register")

    assert incident_db.list_gt_entities("Burglary002")[0]["type"] == "human"
    assert incident_db.list_gt_instruments("Burglary002")[0]["name"] == "crowbar"
    assert incident_db.list_gt_assets("Burglary002")[0]["name"] == "cash register"


def test_record_and_list_matches_is_insert_or_replace(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident(incident_db)
    incident_db.add_incident_entity(incident_id, model_run_id, entity_id="E1", type="human", description="a person")
    incident_db.insert_gt_incident(incident_id, fields={"type": "burglary"})
    incident_db.add_gt_entity(incident_id, entity_id="GE1", type="human", description="a person in dark clothing")

    incident_db.record_entity_match(
        incident_id=incident_id, model_run_id=model_run_id, entity_id="E1", gt_entity_id="GE1", similarity_score=0.91
    )
    matches = incident_db.list_entity_matches(incident_id, model_run_id)
    assert len(matches) == 1
    assert matches[0]["gt_entity_id"] == "GE1"
    assert matches[0]["similarity_score"] == 0.91

    # Re-recording the same (incident_id, model_run_id, entity_id) replaces, not duplicates.
    incident_db.record_entity_match(
        incident_id=incident_id, model_run_id=model_run_id, entity_id="E1", gt_entity_id="GE1", similarity_score=0.97
    )
    matches = incident_db.list_entity_matches(incident_id, model_run_id)
    assert len(matches) == 1
    assert matches[0]["similarity_score"] == 0.97


def test_instrument_and_asset_matches_roundtrip(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident(incident_db)
    incident_db.add_incident_instrument(incident_id, model_run_id, instrument_id="I1", name="crowbar")
    incident_db.add_incident_asset(incident_id, model_run_id, asset_id="A1", name="atm")
    incident_db.insert_gt_incident(incident_id, fields={"type": "burglary"})
    incident_db.add_gt_instrument(incident_id, instrument_id="GI1", name="crowbar")
    incident_db.add_gt_asset(incident_id, asset_id="GA1", name="atm")

    incident_db.record_instrument_match(
        incident_id=incident_id,
        model_run_id=model_run_id,
        instrument_id="I1",
        gt_instrument_id="GI1",
        similarity_score=0.8,
    )
    incident_db.record_asset_match(
        incident_id=incident_id, model_run_id=model_run_id, asset_id="A1", gt_asset_id="GA1", similarity_score=0.85
    )
    assert incident_db.list_instrument_matches(incident_id, model_run_id)[0]["gt_instrument_id"] == "GI1"
    assert incident_db.list_asset_matches(incident_id, model_run_id)[0]["gt_asset_id"] == "GA1"


def test_reports_table_generated_document_crud(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident(incident_db)
    incident_db.insert_generated_report(
        "RPT-1", incident_id=incident_id, model_run_id=model_run_id, filepath="reports/RPT-1.pdf"
    )
    row = incident_db.get_generated_report("RPT-1")
    assert row["incident_id"] == incident_id
    assert row["filepath"] == "reports/RPT-1.pdf"
    assert len(incident_db.list_generated_reports(incident_id=incident_id)) == 1
