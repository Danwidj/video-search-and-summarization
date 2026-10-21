# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for mock POST /api/v1/incidents/search endpoint in search_profile_mock."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from search_profile_mock.app import create_app
from search_profile_mock.routers.incident_search import SearchRequest

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "contracts" / "search-contract-v1" / "fixtures"


def test_search_minimal_request_returns_200():
    client = TestClient(create_app())
    resp = client.post("/api/v1/incidents/search", json={"query": "knife"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "knife"
    assert data["total_hits"] > 0
    assert len(data["hits"]) == data["total_hits"]
    hit = data["hits"][0]
    assert hit["rank"] == 1
    assert "result_id" in hit
    assert "item" in hit
    assert "incident" in hit
    assert "critic" in hit
    assert hit["critic"]["verdict"] in ("confirmed", "rejected", "unverified")


def test_search_filters_by_item_type():
    client = TestClient(create_app())
    resp = client.post("/api/v1/incidents/search", json={"query": "vehicle", "filters": {"item_types": ["asset"]}})
    assert resp.status_code == 200
    data = resp.json()
    for hit in data["hits"]:
        assert hit["item"]["item_type"] == "asset"


def test_search_filters_by_incident_type():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/search",
        json={"query": "burglary tool", "filters": {"incident_types": ["burglary"]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    for hit in data["hits"]:
        assert hit["incident"]["incident_type"] == "burglary"


def test_search_filters_by_road_accident_taxonomy():
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/incidents/search",
        json={"query": "collision", "filters": {"incident_types": ["road accident"]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_hits"] == 1
    assert data["hits"][0]["incident"]["incident_type"] == "road accident"


def test_search_respects_top_k():
    client = TestClient(create_app())
    resp = client.post("/api/v1/incidents/search", json={"query": "threat", "top_k": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["hits"]) <= 2
    assert data["total_hits"] <= 2


def test_search_rejects_missing_query():
    client = TestClient(create_app())
    resp = client.post("/api/v1/incidents/search", json={})
    assert resp.status_code == 422


def test_contract_fixture_valid_minimal_request():
    data = json.loads((FIXTURES_DIR / "valid" / "minimal-request.json").read_text())
    req = SearchRequest.model_validate(data)
    assert req.query == "sharp weapon"
    assert req.top_k == 10
    assert req.min_similarity == 0.0
    assert req.hide_rejected is True
    assert req.filters is None


def test_contract_fixture_valid_full_request():
    data = json.loads((FIXTURES_DIR / "valid" / "full-request.json").read_text())
    req = SearchRequest.model_validate(data)
    assert req.query == "person holding machete or knife"
    assert req.top_k == 5
    assert req.min_similarity == 0.35
    assert req.hide_rejected is True
    assert req.filters is not None
    assert req.filters.incident_types == ["assault", "burglary"]
    assert req.filters.item_types == ["entity", "instrument"]
    assert req.filters.min_severity == 2
    assert req.filters.max_severity == 5


def test_contract_fixture_invalid_requests():
    for name in ("request-missing-query.json", "request-invalid-top-k.json", "request-invalid-item-type.json"):
        data = json.loads((FIXTURES_DIR / "invalid" / name).read_text())
        with pytest.raises(ValidationError):
            SearchRequest.model_validate(data)


def test_search_hide_rejected_filter():
    client = TestClient(create_app())
    resp_hidden = client.post("/api/v1/incidents/search", json={"query": "device", "min_similarity": 0.0})
    assert resp_hidden.status_code == 200
    hits_hidden = resp_hidden.json()["hits"]
    assert all(h["critic"]["verdict"] != "rejected" for h in hits_hidden)

    resp_shown = client.post(
        "/api/v1/incidents/search",
        json={"query": "device", "min_similarity": 0.0, "hide_rejected": False},
    )
    assert resp_shown.status_code == 200
    hits_shown = resp_shown.json()["hits"]
    assert any(h["critic"]["verdict"] == "rejected" for h in hits_shown)

