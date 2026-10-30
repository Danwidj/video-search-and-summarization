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

"""Unit tests for ``POST /api/v1/incidents/match-judge``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vss_agents.api.incident_match_judge import (
    CandidateIncident,
    judge_candidate,
    register_incident_match_judge_routes,
)


def _client() -> TestClient:
    app = FastAPI()
    register_incident_match_judge_routes(app)
    return TestClient(app)


# --- pure scoring unit tests ---


def _candidate(
    incident_id: int = 1,
    incident_type: str = "burglary",
    location: str | None = "Main Street parking lot",
    recorded_at_start: int | None = None,
    recorded_at_end: int | None = None,
) -> CandidateIncident:
    return CandidateIncident(
        incident_id=incident_id,
        overview={"type": incident_type, "location": location},
        recorded_at_start=recorded_at_start,
        recorded_at_end=recorded_at_end,
    )


def test_type_mismatch_returns_zero():
    result = judge_candidate(
        new_incident_type="burglary",
        new_location="Main Street",
        new_recorded_start=None,
        new_recorded_end=None,
        candidate=_candidate(incident_type="road accident"),
    )
    assert result.score == 0.0
    assert any("mismatch" in r for r in result.reasons)


def test_type_match_exact_location_yields_high_score():
    result = judge_candidate(
        new_incident_type="burglary",
        new_location="Main Street parking lot",
        new_recorded_start=None,
        new_recorded_end=None,
        candidate=_candidate(incident_type="burglary", location="Main Street parking lot"),
    )
    # type (0.45) + location full match (0.40) = 0.85
    assert result.score >= 0.8
    assert any("match" in r.lower() for r in result.reasons)


def test_type_match_no_location_overlap_gives_base_score():
    result = judge_candidate(
        new_incident_type="burglary",
        new_location="Harbour Bridge",
        new_recorded_start=None,
        new_recorded_end=None,
        candidate=_candidate(incident_type="burglary", location="Downtown Mall"),
    )
    # type (0.45) + no location overlap (0.0) = 0.45
    assert result.score == pytest.approx(0.45, abs=0.01)


def test_time_overlap_adds_bonus():
    result = judge_candidate(
        new_incident_type="assault",
        new_location="Park Ave",
        new_recorded_start=1000,
        new_recorded_end=1060,
        candidate=_candidate(
            incident_type="assault",
            location="Park Ave",
            recorded_at_start=1050,
            recorded_at_end=1120,
        ),
    )
    # type (0.45) + location full match (0.40) + time bonus (0.15) = 1.0
    assert result.score == pytest.approx(1.0, abs=0.01)
    assert any("overlap" in r.lower() for r in result.reasons)


def test_time_no_overlap_adds_no_bonus():
    result = judge_candidate(
        new_incident_type="assault",
        new_location="Park Ave",
        new_recorded_start=1000,
        new_recorded_end=1060,
        candidate=_candidate(
            incident_type="assault",
            location="Park Ave",
            recorded_at_start=2000,
            recorded_at_end=2060,
        ),
    )
    # no time bonus
    assert result.score < 0.9
    assert any("not overlap" in r.lower() for r in result.reasons)


def test_missing_location_on_new_video_gives_neutral_location_score():
    result = judge_candidate(
        new_incident_type="explosion",
        new_location=None,
        new_recorded_start=None,
        new_recorded_end=None,
        candidate=_candidate(incident_type="explosion", location="Warehouse District"),
    )
    # location neutral (0.5) → type (0.45) + 0.5 * 0.40 = 0.65
    assert result.score == pytest.approx(0.45 + 0.5 * 0.40, abs=0.01)
    assert any("not available" in r.lower() for r in result.reasons)


def test_score_clamped_between_0_and_1():
    result = judge_candidate(
        new_incident_type="burglary",
        new_location="test location alpha beta",
        new_recorded_start=100,
        new_recorded_end=200,
        candidate=_candidate(
            incident_type="burglary",
            location="test location alpha beta",
            recorded_at_start=150,
            recorded_at_end=250,
        ),
    )
    assert 0.0 <= result.score <= 1.0


# --- HTTP endpoint tests ---


def test_endpoint_returns_one_judgement_per_candidate():
    client = _client()
    body = {
        "analysis": {"incident": {"type": "burglary", "location": "High Street"}},
        "candidates": [
            {"incident_id": 10, "overview": {"type": "burglary", "location": "High Street"}},
            {"incident_id": 11, "overview": {"type": "road accident", "location": "High Street"}},
        ],
    }
    response = client.post("/api/v1/incidents/match-judge", json=body)
    assert response.status_code == 200
    data = response.json()
    assert len(data["judgements"]) == 2
    ids = {j["incident_id"] for j in data["judgements"]}
    assert ids == {10, 11}


def test_type_mismatch_candidate_scores_zero_via_http():
    client = _client()
    body = {
        "analysis": {"incident": {"type": "burglary", "location": "Main Street"}},
        "candidates": [
            {"incident_id": 5, "overview": {"type": "road accident", "location": "Main Street"}},
        ],
    }
    response = client.post("/api/v1/incidents/match-judge", json=body)
    assert response.status_code == 200
    judgements = response.json()["judgements"]
    assert judgements[0]["score"] == 0.0


def test_scores_are_between_0_and_1():
    client = _client()
    body = {
        "analysis": {"incident": {"type": "explosion", "location": "Docklands"}},
        "recorded_at_start": 1700000000,
        "recorded_at_end": 1700000060,
        "candidates": [
            {
                "incident_id": 1,
                "overview": {"type": "explosion", "location": "Docklands"},
                "recorded_at_start": 1700000030,
                "recorded_at_end": 1700000090,
            },
        ],
    }
    response = client.post("/api/v1/incidents/match-judge", json=body)
    assert response.status_code == 200
    for j in response.json()["judgements"]:
        assert 0.0 <= j["score"] <= 1.0


def test_each_judgement_has_at_least_one_reason():
    client = _client()
    body = {
        "analysis": {"incident": {"type": "assault", "location": "Park"}},
        "candidates": [
            {"incident_id": 99, "overview": {"type": "assault", "location": "Park"}},
        ],
    }
    response = client.post("/api/v1/incidents/match-judge", json=body)
    assert response.status_code == 200
    for j in response.json()["judgements"]:
        assert len(j["reasons"]) >= 1


def test_empty_candidates_list_returns_422():
    client = _client()
    body = {
        "analysis": {"incident": {"type": "burglary"}},
        "candidates": [],
    }
    response = client.post("/api/v1/incidents/match-judge", json=body)
    assert response.status_code == 422


def test_missing_analysis_returns_422():
    client = _client()
    body = {"candidates": [{"incident_id": 1, "overview": {"type": "burglary"}}]}
    response = client.post("/api/v1/incidents/match-judge", json=body)
    assert response.status_code == 422
