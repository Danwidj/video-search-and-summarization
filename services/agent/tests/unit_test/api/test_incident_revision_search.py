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

"""Unit tests for ``POST /api/v1/incidents/revisions/search``."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from vss_agents.api.incident_revision_search import create_incident_revision_search_router
from vss_agents.api.incident_search import EmbeddingUnavailableError

HIT = {
    "revision_id": 7,
    "video_id": "v1",
    "revision_no": 2,
    "kind": "ai",
    "model_run_id": "run-1",
    "title": "Fight at the bus stop",
    "description": "Two people fight.",
    "incident_type": "assault",
    "severity_level": 4,
    "start_seconds": 2,
    "end_seconds": 9,
    "similarity_score": 0.87,
}


def _client(*, rows=None, query_embedder=None, db_available=True) -> tuple[TestClient, MagicMock, MagicMock]:
    db = MagicMock()
    db.search_revisions = AsyncMock(return_value=[] if rows is None else rows)
    embedder = MagicMock()
    embedder.embed_query = AsyncMock(return_value=[0.1] * 1024) if query_embedder is None else query_embedder
    app = FastAPI()
    app.include_router(create_incident_revision_search_router(embedder))
    patcher = patch(
        "vss_agents.api.incident_revision_search.incident_db.get_db",
        new_callable=AsyncMock,
        return_value=db if db_available else None,
    )
    patcher.start()
    client = TestClient(app)
    client.__dict__["_patcher"] = patcher
    return client, db, embedder


def _stop(client: TestClient) -> None:
    client.__dict__["_patcher"].stop()


def test_returns_the_nearest_revisions_with_their_facets():
    client, db, embedder = _client(rows=[HIT])
    try:
        response = client.post("/api/v1/incidents/revisions/search", json={"query": "man fighting", "top_k": 3})
    finally:
        _stop(client)
    assert response.status_code == 200
    assert response.json() == [HIT]
    embedder.embed_query.assert_awaited_once_with("man fighting")
    db.search_revisions.assert_awaited_once_with([0.1] * 1024, top_k=3, min_similarity=0.0)


def test_empty_result_is_an_empty_list():
    client, _, _ = _client(rows=[])
    try:
        response = client.post("/api/v1/incidents/revisions/search", json={"query": "nothing like this"})
    finally:
        _stop(client)
    assert response.status_code == 200 and response.json() == []


def test_missing_embedding_key_is_503_and_skips_the_database_search():
    client, db, _ = _client(query_embedder=AsyncMock(side_effect=EmbeddingUnavailableError("no key")))
    try:
        response = client.post("/api/v1/incidents/revisions/search", json={"query": "fight"})
    finally:
        _stop(client)
    assert response.status_code == 503 and "no key" in response.json()["detail"]
    db.search_revisions.assert_not_called()


def test_embedding_endpoint_failure_is_502():
    client, db, _ = _client(query_embedder=AsyncMock(side_effect=httpx.ConnectError("down")))
    try:
        response = client.post("/api/v1/incidents/revisions/search", json={"query": "fight"})
    finally:
        _stop(client)
    assert response.status_code == 502
    db.search_revisions.assert_not_called()


def test_unavailable_database_is_503():
    client, _, _ = _client(db_available=False)
    try:
        response = client.post("/api/v1/incidents/revisions/search", json={"query": "fight"})
    finally:
        _stop(client)
    assert response.status_code == 503


def test_request_bounds_are_validated():
    client, _, _ = _client()
    try:
        assert client.post("/api/v1/incidents/revisions/search", json={"query": ""}).status_code == 422
        assert client.post("/api/v1/incidents/revisions/search", json={"query": "x", "top_k": 0}).status_code == 422
        assert client.post("/api/v1/incidents/revisions/search", json={"query": "x", "top_k": 51}).status_code == 422
        assert (
            client.post("/api/v1/incidents/revisions/search", json={"query": "x", "min_similarity": 1.5}).status_code
            == 422
        )
    finally:
        _stop(client)
