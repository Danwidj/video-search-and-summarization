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

"""Unit tests for ``POST /api/v1/incidents/evidence-embeddings``."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from vss_agents.api.incident_evidence_embeddings import create_incident_evidence_embeddings_router
from vss_agents.api.incident_evidence_embeddings import passage_text

EVIDENCE = [
    {"item_type": "entity", "item_id": "E1", "item_name": "human", "description": "Person in a hood.", "image": "k1"},
    {"item_type": "instrument", "item_id": "I1", "item_name": "crowbar", "description": "Used on A1.", "image": None},
    {"description": "no identity, skipped"},
]


def _client(*, revision, embedder=None, db_available=True) -> tuple[TestClient, MagicMock]:
    db = MagicMock()
    db.get_revision = AsyncMock(return_value=revision)
    app = FastAPI()
    app.include_router(create_incident_evidence_embeddings_router(embedder))
    patcher = patch(
        "vss_agents.api.incident_evidence_embeddings.incident_db.get_db",
        new_callable=AsyncMock,
        return_value=db if db_available else None,
    )
    patcher.start()
    client = TestClient(app)
    client.__dict__["_patcher"] = patcher
    return client, db


def _embedder(vectors=None, *, configured=True, error=None) -> MagicMock:
    embedder = MagicMock()
    embedder.is_configured.return_value = configured
    embedder.embed = AsyncMock(return_value=vectors, side_effect=error)
    return embedder


def _stop(client: TestClient) -> None:
    client.__dict__["_patcher"].stop()


def test_returns_one_passage_embedding_per_evidence_item():
    embedder = _embedder([[0.1, 0.2], [0.3, 0.4]])
    client, db = _client(revision={"id": 7, "evidence": EVIDENCE}, embedder=embedder)
    try:
        response = client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7})
    finally:
        _stop(client)
    assert response.status_code == 200
    assert response.json() == [
        {"item_type": "entity", "item_id": "E1", "embedding": [0.1, 0.2]},
        {"item_type": "instrument", "item_id": "I1", "embedding": [0.3, 0.4]},
    ]
    db.get_revision.assert_awaited_once_with(7)
    embedder.embed.assert_awaited_once_with(["human: Person in a hood.", "crowbar: Used on A1."], input_type="passage")


def test_unknown_revision_is_404():
    client, _ = _client(revision=None, embedder=_embedder([]))
    try:
        assert client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7}).status_code == 404
    finally:
        _stop(client)


def test_revision_without_evidence_returns_an_empty_list_without_calling_the_embedder():
    embedder = _embedder([])
    client, _ = _client(revision={"id": 7, "evidence": []}, embedder=embedder)
    try:
        response = client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7})
    finally:
        _stop(client)
    assert response.status_code == 200 and response.json() == []
    embedder.embed.assert_not_awaited()


def test_unavailable_database_or_embedding_key_is_503():
    client, _ = _client(revision=None, embedder=_embedder([]), db_available=False)
    try:
        assert client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7}).status_code == 503
    finally:
        _stop(client)
    client, _ = _client(revision={"id": 7, "evidence": EVIDENCE}, embedder=_embedder(configured=False))
    try:
        assert client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7}).status_code == 503
    finally:
        _stop(client)


def test_embedding_endpoint_failure_is_502():
    client, _ = _client(revision={"id": 7, "evidence": EVIDENCE}, embedder=_embedder(error=httpx.ConnectError("down")))
    try:
        assert client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7}).status_code == 502
    finally:
        _stop(client)


def test_revision_id_must_be_a_positive_integer():
    client, _ = _client(revision=None, embedder=_embedder([]))
    try:
        assert client.post("/api/v1/incidents/evidence-embeddings", json={}).status_code == 422
        assert client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 0}).status_code == 422
    finally:
        _stop(client)


def test_evidence_in_the_body_is_embedded_without_reading_a_revision():
    embedder = _embedder([[0.1, 0.2]])
    client, db = _client(revision=None, embedder=embedder, db_available=False)
    try:
        response = client.post(
            "/api/v1/incidents/evidence-embeddings",
            json={
                "evidence": [
                    {"item_type": "entity", "item_id": "E1", "item_name": "human", "description": "Person in a hood."}
                ]
            },
        )
    finally:
        _stop(client)
    assert response.status_code == 200
    assert response.json() == [{"item_type": "entity", "item_id": "E1", "embedding": [0.1, 0.2]}]
    embedder.embed.assert_awaited_once_with(["human: Person in a hood."], input_type="passage")
    db.get_revision.assert_not_awaited()


def test_empty_evidence_list_returns_nothing_without_calling_the_embedder():
    embedder = _embedder([])
    client, _ = _client(revision=None, embedder=embedder)
    try:
        response = client.post("/api/v1/incidents/evidence-embeddings", json={"evidence": []})
    finally:
        _stop(client)
    assert response.status_code == 200 and response.json() == []
    embedder.embed.assert_not_awaited()


def test_body_must_name_exactly_one_source():
    client, _ = _client(revision=None, embedder=_embedder([]))
    try:
        assert (
            client.post("/api/v1/incidents/evidence-embeddings", json={"revision_id": 7, "evidence": []}).status_code
            == 422
        )
    finally:
        _stop(client)


def test_passage_text_matches_the_evidence_description_convention():
    assert passage_text({"item_name": "door", "description": "Forced open."}) == "door: Forced open."
