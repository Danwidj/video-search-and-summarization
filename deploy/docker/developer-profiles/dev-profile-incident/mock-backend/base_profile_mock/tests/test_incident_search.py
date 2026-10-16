# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for mock POST /api/v1/incidents/search endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from base_profile_mock.app import create_app


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
    resp = client.post("/api/v1/incidents/search", json={"query": "vehicle", "item_types": ["asset"]})
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
