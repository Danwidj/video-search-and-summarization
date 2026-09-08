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

"""Additive schema: is_synthetic / duration_sec / model_version + evidence tables."""

from __future__ import annotations

from db import IncidentDB, metadata


def test_new_tables_and_columns_present(incident_db: IncidentDB):
    names = set(metadata.tables)
    assert {"incident_entities", "incident_instruments", "incident_assets"} <= names
    cols = {c.name for c in metadata.tables["incident_reports"].columns}
    assert {"is_synthetic", "duration_sec", "model_version"} <= cols
    for table in ("incident_entities", "incident_instruments", "incident_assets"):
        assert "image_key" in {c.name for c in metadata.tables[table].columns}
    assert "duration_sec" in {c.name for c in metadata.tables["videos"].columns}


def test_report_carries_additive_fields(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="c.mp4", r2_key="normal_videos/c.mp4", duration_sec=42)
    assert incident_db.get_video(vid)["duration_sec"] == 42

    rid = incident_db.insert_report(
        video_id=vid,
        report={
            "incident_type": "warehouse safety",
            "severity": 3,
            "duration_sec": 15,
            "model_version": "mock-seed-v1",
            "is_synthetic": True,
        },
    )
    row = incident_db.get_report(rid)
    assert row["is_synthetic"] is True
    assert row["duration_sec"] == 15
    assert row["model_version"] == "mock-seed-v1"

    incident_db.update_report(rid, fields={"duration_sec": 20, "model_version": "v2"}, edited_by="q")
    row = incident_db.get_report(rid)
    assert row["duration_sec"] == 20
    assert row["model_version"] == "v2"


def test_insert_report_defaults_is_synthetic_true(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="d.mp4")
    rid = incident_db.insert_report(video_id=vid, report={"incident_type": "traffic", "severity": 2})
    assert incident_db.get_report(rid)["is_synthetic"] is True


def test_evidence_crud_roundtrip(incident_db: IncidentDB):
    vid = incident_db.insert_video(filename="e.mp4", r2_key="normal_videos/e.mp4")
    rid = incident_db.insert_report(video_id=vid, report={"incident_type": "equipment", "severity": 3})

    incident_db.add_incident_entity(rid, local_id="E1", type="human", description="operator")
    incident_db.add_incident_instrument(
        rid, local_id="I1", entity_local_id="E1", name="forklift", description="laden", threat_level=3
    )
    incident_db.add_incident_asset(rid, local_id="A1", name="racking", description="loaded bay")

    entities = incident_db.list_incident_entities(rid)
    instruments = incident_db.list_incident_instruments(rid)
    assets = incident_db.list_incident_assets(rid)
    assert [e["local_id"] for e in entities] == ["E1"]
    assert entities[0]["type"] == "human"
    assert entities[0]["is_synthetic"] is True
    assert instruments[0]["threat_level"] == 3
    assert instruments[0]["entity_local_id"] == "E1"
    assert assets[0]["name"] == "racking"

    # Scoped to the report; another report sees nothing.
    other = incident_db.insert_report(video_id=vid, report={"incident_type": "traffic", "severity": 1})
    assert incident_db.list_incident_entities(other) == []

    incident_db.clear_incident_evidence(rid)
    assert incident_db.list_incident_entities(rid) == []
    assert incident_db.list_incident_instruments(rid) == []
    assert incident_db.list_incident_assets(rid) == []


def test_upsert_video_by_r2_key_is_stable(incident_db: IncidentDB):
    first = incident_db.upsert_video_by_r2_key(r2_key="normal_videos/x.mp4", filename="x.mp4", duration_sec=10)
    again = incident_db.upsert_video_by_r2_key(r2_key="normal_videos/x.mp4", filename="x.mp4", duration_sec=99)
    assert first == again
    assert incident_db.get_video(first)["duration_sec"] == 99
    assert len(incident_db.list_videos()) == 1


def test_link_report_video_sets_a_stable_fk(incident_db: IncidentDB):
    v1 = incident_db.insert_video(filename="a.mp4", r2_key="normal_videos/a.mp4")
    v2 = incident_db.insert_video(filename="b.mp4", r2_key="normal_videos/b.mp4")
    rid = incident_db.insert_report(video_id=v1, report={"incident_type": "traffic", "severity": 2})
    assert incident_db.get_report_by_video_id(v1)["id"] == rid

    incident_db.link_report_video(rid, v2, edited_by="reviewer")
    assert incident_db.get_report(rid)["video_id"] == v2
    assert incident_db.get_report(rid)["edited_by"] == "reviewer"
