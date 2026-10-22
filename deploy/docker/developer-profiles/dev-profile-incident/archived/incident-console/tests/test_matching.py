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

"""Similarity-based matching: assignment correctness, threshold filtering, persistence."""

from __future__ import annotations

import re
from collections import Counter
from unittest.mock import patch

import pytest

import embed_client
import matching
from db import IncidentDB
from matching import Assignment, match_incident, match_kind, solve_assignment


def test_solve_assignment_picks_the_optimal_one_to_one_pairing():
    # A greedy row-by-row pick would take row0's best column (col0, 0.9),
    # forcing row1 onto col1 (0.1), total 1.0. The optimal assignment instead
    # takes (row0, col1)=0.8 and (row1, col0)=0.85, total 1.65.
    matrix = [
        [0.9, 0.8],
        [0.85, 0.1],
    ]
    result = solve_assignment(matrix, threshold=0.0)
    assert {(a.index, a.gt_index) for a in result} == {(0, 1), (1, 0)}
    scores = {(a.index, a.gt_index): a.similarity for a in result}
    assert scores[(0, 1)] == 0.8
    assert scores[(1, 0)] == 0.85


def test_solve_assignment_filters_below_threshold():
    matrix = [
        [0.95, 0.2],
        [0.3, 0.4],
    ]
    result = solve_assignment(matrix, threshold=0.5)
    # Optimal pairing is (0,0)=0.95 and (1,1)=0.4; the second clears no bar,
    # a forced low-similarity pairing is discarded rather than accepted.
    assert len(result) == 1
    assert result[0] == Assignment(index=0, gt_index=0, similarity=0.95)


def test_solve_assignment_handles_empty_input():
    assert solve_assignment([], threshold=0.5) == []


def _seed_incident_with_evidence(db: IncidentDB, *, incident_id="Burglary001", model_run_id="MR-1"):
    db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4")
    db.insert_model_run(model_run_id, model_name="incident-vlm", prompt_version="p1")
    db.insert_incident(incident_id, model_run_id, fields={"type": "burglary", "severity_level": 3})
    db.add_incident_entity(
        incident_id, model_run_id, entity_id="E1", type="human", description="person in a red hoodie"
    )
    db.add_incident_entity(
        incident_id, model_run_id, entity_id="E2", type="human", description="person in a black shirt"
    )

    db.insert_gt_incident(incident_id, fields={"type": "burglary"})
    db.add_gt_entity(incident_id, entity_id="GE1", type="human", description="person wearing a black shirt")
    db.add_gt_entity(incident_id, entity_id="GE2", type="human", description="person wearing a red hoodie")
    return incident_id, model_run_id


def _fake_embed(texts):
    """Deterministic bag-of-words term-count vectors, no network.

    Cosine similarity over these behaves like a crude but real embedding: two
    texts sharing every word score 1.0, texts sharing some words score
    somewhere in between, and disjoint texts score 0 - enough graded signal to
    exercise both the assignment solver and the threshold cutoff.
    """
    tokenized = [re.findall(r"[a-z']+", text.lower()) for text in texts]
    vocab = sorted({word for tokens in tokenized for word in tokens})
    vectors = [[float(Counter(tokens).get(word, 0)) for word in vocab] for tokens in tokenized]
    return embed_client.Result(ok=True, data=vectors)


def test_match_kind_persists_only_accepted_matches(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident_with_evidence(incident_db)
    with patch.object(matching, "embed_texts", side_effect=_fake_embed):
        persisted = match_kind(incident_db, "entities", incident_id, model_run_id, threshold=0.5)

    # E1 ("red hoodie") should pair with GE2 ("red hoodie"); E2 ("black shirt")
    # should pair with GE1 ("black shirt") - the cross pairing shares fewer words.
    by_entity = {row["entity_id"]: row["gt_entity_id"] for row in persisted}
    assert by_entity == {"E1": "GE2", "E2": "GE1"}

    stored = incident_db.list_entity_matches(incident_id, model_run_id)
    assert {(row["entity_id"], row["gt_entity_id"]) for row in stored} == {("E1", "GE2"), ("E2", "GE1")}
    for row in stored:
        assert row["similarity_score"] >= 0.5


def test_match_kind_discards_pairs_below_threshold(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident_with_evidence(incident_db)
    with patch.object(matching, "embed_texts", side_effect=_fake_embed):
        persisted = match_kind(incident_db, "entities", incident_id, model_run_id, threshold=0.99)

    assert persisted == []
    assert incident_db.list_entity_matches(incident_id, model_run_id) == []


def test_match_kind_is_empty_when_no_ground_truth(incident_db: IncidentDB):
    incident_id, model_run_id = "NoGT001", "MR-1"
    incident_db.upsert_video(incident_id, filepath=f"normal_videos/{incident_id}.mp4")
    incident_db.insert_model_run(model_run_id, model_name="incident-vlm", prompt_version="p1")
    incident_db.insert_incident(incident_id, model_run_id, fields={"type": "explosion", "severity_level": 2})
    incident_db.add_incident_entity(
        incident_id, model_run_id, entity_id="E1", type="unknown", description="figure in smoke"
    )

    with patch.object(matching, "embed_texts", side_effect=_fake_embed):
        persisted = match_kind(incident_db, "entities", incident_id, model_run_id)
    assert persisted == []
    assert incident_db.list_entity_matches(incident_id, model_run_id) == []


def test_match_incident_covers_all_three_kinds(incident_db: IncidentDB):
    incident_id, model_run_id = _seed_incident_with_evidence(incident_db)
    incident_db.add_incident_instrument(
        incident_id, model_run_id, instrument_id="I1", name="crowbar", description="metal crowbar"
    )
    incident_db.add_gt_instrument(incident_id, instrument_id="GI1", name="crowbar", description="metal crowbar")
    incident_db.add_incident_asset(
        incident_id, model_run_id, asset_id="A1", name="atm machine", description="atm at the counter"
    )
    incident_db.add_gt_asset(incident_id, asset_id="GA1", name="atm machine", description="atm at the counter")

    with patch.object(matching, "embed_texts", side_effect=_fake_embed):
        result = match_incident(incident_db, incident_id, model_run_id)

    assert set(result) == {"entities", "instruments", "assets"}
    assert len(result["instruments"]) == 1
    assert result["instruments"][0]["instrument_id"] == "I1"
    assert result["instruments"][0]["gt_instrument_id"] == "GI1"
    assert result["instruments"][0]["similarity_score"] == pytest.approx(1.0)
    assert len(result["assets"]) == 1
    assert result["assets"][0]["asset_id"] == "A1"
    assert result["assets"][0]["gt_asset_id"] == "GA1"
    assert result["assets"][0]["similarity_score"] == pytest.approx(1.0)
