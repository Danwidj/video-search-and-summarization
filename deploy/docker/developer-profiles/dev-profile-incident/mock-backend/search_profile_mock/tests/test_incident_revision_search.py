# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from fastapi.testclient import TestClient

from search_profile_mock.app import create_app
from search_profile_mock.routers.incident_revision_search import RevisionSearchHit


def test_revision_search_returns_hits_shaped_like_agent():
    resp = TestClient(create_app()).post("/api/v1/incidents/revisions/search", json={"query": "knife"})
    assert resp.status_code == 200
    hits = [RevisionSearchHit.model_validate(h) for h in resp.json()]
    assert hits
    assert [h.similarity_score for h in hits] == sorted((h.similarity_score for h in hits), reverse=True)


def test_revision_search_honours_top_k_and_min_similarity():
    client = TestClient(create_app())
    assert len(client.post("/api/v1/incidents/revisions/search", json={"query": "x", "top_k": 1}).json()) == 1
    hits = client.post("/api/v1/incidents/revisions/search", json={"query": "x", "min_similarity": 0.8}).json()
    assert hits and all(h["similarity_score"] >= 0.8 for h in hits)


def test_revision_search_rejects_empty_query():
    resp = TestClient(create_app()).post("/api/v1/incidents/revisions/search", json={"query": ""})
    assert resp.status_code == 422
