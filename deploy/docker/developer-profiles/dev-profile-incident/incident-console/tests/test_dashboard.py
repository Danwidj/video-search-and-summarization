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

"""Fixture integrity and dashboard interactions without a database.

The seed is parsed from fixtures/data/*.csv: the group's real ground-truth
incidents (``synthetic`` false) plus a generated synthetic half (``synthetic``
true). Known ground-truth gaps are asserted explicitly so a regression in the
parser is visible rather than silently "fixed".
"""

import re
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from dashboard_view import frame, review_queue
from fixtures.dashboard_seed import load_seed

TYPES = {"animal", "road accident", "burglary", "explosion", "fighting"}
TIMESTAMP = re.compile(r"\d{2}:\d{2}:\d{2}")
# Ground-truth rows with no incident row of their own / no severity in the sheet.
EMPTY_INCIDENTS = {"Burglary005", "Burglary006", "Explosion007"}
STRAY_ENTITY_INCIDENT = "RoadAccidents006"


def test_real_and_synthetic_split():
    seed = load_seed()
    incidents = seed["Incident"]
    real = [r for r in incidents if r["synthetic"] is False]
    synthetic = [r for r in incidents if r["synthetic"] is True]
    assert len(real) == 36
    assert len(synthetic) == 36
    assert len(incidents) == len(real) + len(synthetic)
    assert {r["Incident_ID"] for r in real} == {
        f"{prefix}{i:03d}"
        for prefix, count in (("Burglary", 7), ("Explosion", 9), ("RoadAccidents", 5), ("Animal", 15))
        for i in range(1, count + 1)
    }
    assert all(r["Incident_ID"].startswith("SYN-") for r in synthetic)
    # The synthetic half fills gaps the real data lacks.
    assert any(r["Type"] == "fighting" and r["synthetic"] for r in incidents)
    assert not any(r["Type"] == "fighting" and not r["synthetic"] for r in incidents)


def test_synthetic_flag_present_and_consistent():
    seed = load_seed()
    for name in ("Incident", "Entity", "Instrument", "Asset"):
        assert seed[name], name
        for row in seed[name]:
            assert row["synthetic"] in (True, False), (name, row)
    incident_flag = {r["Incident_ID"]: r["synthetic"] for r in seed["Incident"]}
    for name in ("Entity", "Instrument", "Asset"):
        for row in seed[name]:
            if row["Incident_ID"] in incident_flag:
                assert row["synthetic"] == incident_flag[row["Incident_ID"]], (name, row)


def test_incident_shapes_and_blank_handling():
    seed = load_seed()
    incidents = {r["Incident_ID"]: r for r in seed["Incident"]}
    for incident_id, row in incidents.items():
        for key in ("Start_Timestamp", "End_Timestamp"):
            assert row[key] is None or TIMESTAMP.fullmatch(row[key]), (incident_id, key, row[key])
        assert row["Duration"] is None or isinstance(row["Duration"], int)
        assert row["Severity"] is None or 1 <= row["Severity"] <= 5
        if incident_id in EMPTY_INCIDENTS:
            assert row["Type"] is None
            assert row["Start_Timestamp"] is None and row["End_Timestamp"] is None
        else:
            assert row["Type"] in TYPES
        # Blank confidence is omitted entirely, never emitted as None/0.
        if "Confidence_Score" in row:
            assert 0 < row["Confidence_Score"] <= 1
    # Real burglary / road-accident severities are blank in the sheet -> carried as None.
    for row in seed["Incident"]:
        if not row["synthetic"] and row["Type"] in {"burglary", "road accident"}:
            assert row["Severity"] is None
        # Real rows never carry a confidence score (all blank in the sheet).
        if not row["synthetic"]:
            assert "Confidence_Score" not in row


def test_low_confidence_queue_has_content():
    seed = load_seed()
    missing = [r for r in seed["Incident"] if "Confidence_Score" not in r]
    low = [r for r in seed["Incident"] if r.get("Confidence_Score", 1) < 0.7]
    assert len(missing) >= 10
    assert len(low) >= 5
    queue = review_queue(frame(seed["Incident"]))
    assert not queue.empty
    # Missing scores sort first, then ascending score.
    assert queue.iloc[0].Confidence_Score != queue.iloc[0].Confidence_Score  # NaN
    scores = queue.Confidence_Score.dropna().tolist()
    assert scores == sorted(scores)
    assert all(score < 0.7 for score in scores)


def test_linked_rows_reference_incidents():
    seed = load_seed()
    incident_ids = {r["Incident_ID"] for r in seed["Incident"]}
    incident_ids_to_filename = {r["Incident_ID"]: r["Filename"] for r in seed["Incident"]}
    entities = {(e["Incident_ID"], e["ID"]) for e in seed["Entity"]}
    for name in ("Entity", "Instrument", "Asset"):
        for row in seed[name]:
            if name == "Entity" and row["Incident_ID"] == STRAY_ENTITY_INCIDENT:
                continue  # known gap: entity for an incident the sheet never lists
            assert row["Incident_ID"] in incident_ids, (name, row)
            assert row["Filename"] == incident_ids_to_filename[row["Incident_ID"]], (name, row)
    for row in seed["Instrument"]:
        if row["Entity_ID"] is None:
            continue  # e.g. Burglary007 truck has no holder in the sheet
        if not row["synthetic"]:
            # Real data has a known gap: RoadAccidents005 instrument I2 points at E2,
            # but that entity row was filed under the stray RoadAccidents006. Carried
            # through as-is; flagged for the group. The synthetic half is kept clean.
            continue
        assert (row["Incident_ID"], row["Entity_ID"]) in entities, row
    by_id = {r["Incident_ID"]: r for r in seed["Incident"]}
    for incident_id in incident_ids:
        count = sum(e["Incident_ID"] == incident_id for e in seed["Entity"])
        if by_id[incident_id]["synthetic"]:
            # Every synthetic incident gets 1-4 linked entities.
            assert 1 <= count <= 4, (incident_id, count)
        elif incident_id in EMPTY_INCIDENTS:
            assert count == 0
        # Real non-empty incidents may still have 0 entities (e.g. every real
        # explosion: the sheet provided no explosion entities at all).


def test_synthetic_fills_explosion_and_confidence_gaps():
    seed = load_seed()
    syn_explosion = {r["Incident_ID"] for r in seed["Incident"] if r["synthetic"] and r["Type"] == "explosion"}
    assert syn_explosion
    assert any(e["Incident_ID"] in syn_explosion for e in seed["Entity"])
    assert any(i["Incident_ID"] in syn_explosion for i in seed["Instrument"])
    assert any(a["Incident_ID"] in syn_explosion for a in seed["Asset"])
    # Synthetic rows carry a spread of confidence: some below 0.7, some missing.
    syn = [r for r in seed["Incident"] if r["synthetic"]]
    assert any("Confidence_Score" not in r for r in syn)
    assert any(r.get("Confidence_Score", 1) < 0.7 for r in syn)
    assert any(r.get("Confidence_Score", 0) >= 0.7 for r in syn)


def test_images_are_none_and_videos_linked_to_incidents():
    seed = load_seed()
    for name in ("Entity", "Instrument", "Asset"):
        assert all(row["Image"] is None for row in seed[name])
    assert len(seed["Video"]) == len(seed["Incident"])
    assert seed["Video"][0]["ID"] == "V1"
    assert {row["Incident_ID"] for row in seed["Video"]} == {row["Incident_ID"] for row in seed["Incident"]}
    assert {row["Filename"] for row in seed["Video"]} == {row["Filename"] for row in seed["Incident"]}
    assert len({row["Filename"] for row in seed["Video"]}) == len(seed["Video"])
    assert all("example.invalid" in v["Filepath"] for v in seed["Video"])
    assert seed["Report"] == [] and seed["Query"] == []


def test_dashboard_preview_filters_reset_and_empty():
    seed = load_seed()
    view = frame(seed["Incident"])
    scored = view[view.Severity.between(1, 5)]
    total = str(len(scored))
    explosion = str(len(scored[scored.Type == "explosion"]))
    with patch("db.is_configured", return_value=False):
        app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=15).run()
        assert not app.exception
        assert app.metric[0].value == total
        app.multiselect[0].set_value(["explosion"]).run()
        assert not app.exception
        assert app.metric[0].value == explosion
        app.multiselect[1].set_value(["bag"]).run()
        assert not app.exception
        assert app.metric[0].value == "0"
        app.button[0].click().run()
        assert app.metric[0].value == total
        app.toggle[0].set_value(False).run()
        assert not app.exception
        assert app.metric[0].value == "0"
