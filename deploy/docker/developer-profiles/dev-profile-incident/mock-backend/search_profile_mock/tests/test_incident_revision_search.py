# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from search_profile_mock.app import create_app
from search_profile_mock.routers.incident_revision_search import RevisionSearchHit


def test_revision_search_returns_hits_shaped_like_agent():
    resp = TestClient(create_app()).post("/api/v1/incidents/revisions/search", json={"query": "assault"})
    assert resp.status_code == 200
    hits = [RevisionSearchHit.model_validate(h) for h in resp.json()]
    assert hits
    assert [h.similarity_score for h in hits] == sorted((h.similarity_score for h in hits), reverse=True)


def test_revision_search_honours_top_k_and_min_similarity():
    client = TestClient(create_app())
    assert len(client.post("/api/v1/incidents/revisions/search", json={"query": "x", "top_k": 1}).json()) == 1
    hits = client.post("/api/v1/incidents/revisions/search", json={"query": "x", "min_similarity": 0.8}).json()
    assert hits and all(h["similarity_score"] >= 0.8 for h in hits)


def test_revision_search_answers_with_finals_video_ids():
    # The console keeps only hits whose video_id is in the finals database, so these must be real finals IDs.
    hits = TestClient(create_app()).post("/api/v1/incidents/revisions/search", json={"query": "assault"}).json()
    assert {"Assault018", "Assault032"} <= {h["video_id"] for h in hits}


def test_revision_search_rejects_empty_query():
    resp = TestClient(create_app()).post("/api/v1/incidents/revisions/search", json={"query": ""})
    assert resp.status_code == 422


def test_snapshot_is_the_base_mocks_not_a_copy():
    # Both mocks answer about the same clips because this one loads base_profile_mock's snapshot file.
    from search_profile_mock import finals_snapshot

    base = finals_snapshot._BASE_SNAPSHOT
    assert base.parts[-4:] == ("base_profile_mock", "src", "base_profile_mock", "finals_snapshot.py")
    assert base.with_name("finals_snapshot.json").is_file()
    assert not (Path(finals_snapshot.__file__).with_name("finals_snapshot.json")).exists()
    assert {h["revision_id"] for h in finals_snapshot.revision_hits()}
