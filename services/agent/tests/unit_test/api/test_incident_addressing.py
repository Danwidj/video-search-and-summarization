# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Incident-addressed agent reads (mvp3 P4.5): incident ids, source video names, multi-camera revisions."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from vss_agents.api.incident_chat import register_incident_chat_routes
from vss_agents.api.incident_evidence_embeddings import create_incident_evidence_embeddings_router
from vss_agents.api.incident_search import SearchFilters
from vss_agents.api.incident_search import SearchRequest
from vss_agents.api.incident_search import SupabaseSearchStore


def _item(item_id: str, name: str, ts: int = 5) -> dict[str, Any]:
    return {
        "item_type": "instrument",
        "item_id": item_id,
        "item_name": name,
        "label": name,
        "description": f"A {name}",
        "timestamp_seconds": ts,
    }


class _Store:
    def __init__(self, revision: dict[str, Any], official: int | None = None) -> None:
        self.revision = revision
        self.official = official

    async def get_revision(self, revision_id: int) -> dict[str, Any] | None:
        return self.revision if revision_id == self.revision["id"] else None

    async def get_official_revision_id(self, incident_id: int) -> int | None:
        return self.official


class _NoSearch:
    async def search(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("a non-official revision must not hit the search index")


def _chat(store: _Store, **extra: Any) -> dict[str, Any]:
    app = FastAPI()
    register_incident_chat_routes(app, search_client=_NoSearch(), revision_store=store)
    resp = TestClient(app).post(
        "/api/v1/incidents/chat",
        json={"messages": [{"role": "user", "content": "what tools?"}], **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_chat_cites_every_camera_of_a_saved_revision() -> None:
    revision = {
        "id": 5,
        "incident_id": 3,
        "video_names": ["front.mp4", "rear.mp4"],
        "evidence": [
            {**_item("I1", "crowbar"), "video_id": "front.mp4", "image": "e/front/I1.jpg"},
            {**_item("I1", "torch"), "video_id": "rear.mp4", "image": "e/rear/I1.jpg"},
        ],
    }
    cits = _chat(_Store(revision), version_id=5)["message"]["citations"]
    assert {(c["incident_id"], c["video_id"], c["item_id"]) for c in cits} == {
        (3, "front.mp4", "I1"),
        (3, "rear.mp4", "I1"),
    }


def test_chat_draft_envelope_uses_each_cameras_items() -> None:
    revision = {
        "id": 5,
        "incident_id": 3,
        "video_names": ["front.mp4", "rear.mp4"],
        "evidence": [{**_item("I1", "crowbar"), "video_id": "front.mp4", "image": "e/front/I1.jpg"}],
    }
    draft = {
        "overview": {"title": "t"},
        "cameras": [
            {"video": "front.mp4", "report": {"instruments": [{"instrument_id": "I1", "name": "crowbar"}]}},
            {"video": "rear.mp4", "report": {"instruments": [{"instrument_id": "I2", "name": "torch"}]}},
        ],
    }
    cits = _chat(_Store(revision), version_id=5, draft_report=draft)["message"]["citations"]
    by_key = {(c["video_id"], c["item_id"]): c for c in cits}
    assert set(by_key) == {("front.mp4", "I1"), ("rear.mp4", "I2")}
    assert by_key[("front.mp4", "I1")]["crop_image_url"].endswith("e/front/I1.jpg")
    assert by_key[("rear.mp4", "I2")]["crop_image_url"] == ""


def test_chat_rejects_a_revision_of_another_incident() -> None:
    store = _Store({"id": 5, "incident_id": 3, "video_names": ["a.mp4"], "evidence": []})
    app = FastAPI()
    register_incident_chat_routes(app, search_client=_NoSearch(), revision_store=store)
    resp = TestClient(app).post(
        "/api/v1/incidents/chat",
        json={
            "messages": [{"role": "user", "content": "x"}],
            "version_id": 5,
            "context": {"scope": "incident", "incident_id": 4},
        },
    )
    assert resp.status_code == 400


def test_search_filters_take_a_numeric_incident_id() -> None:
    assert SearchFilters(incident_id=7).incident_id == 7
    with pytest.raises(ValueError):
        SearchFilters(incident_id=0)
    SearchRequest(query="", filters=SearchFilters(incident_id=7))
    with pytest.raises(ValueError):
        SearchRequest(query="", filters=SearchFilters())


@pytest.mark.asyncio
async def test_supabase_store_sends_p_incident_id_only_when_scoped() -> None:
    calls: list[dict[str, Any]] = []

    def rpc(name: str, params: dict[str, Any]) -> MagicMock:
        calls.append(params)
        query = MagicMock()
        query.execute = AsyncMock(return_value=MagicMock(data=[]))
        return query

    client = MagicMock()
    client.rpc = rpc
    store = SupabaseSearchStore()
    store._get_client = AsyncMock(return_value=client)  # type: ignore[method-assign]
    await store.search_evidence_items([0.1], 5, 0.0, None, None, None, None)
    await store.search_evidence_items(None, 5, 0.0, None, None, None, None, incident_id=9)
    assert "p_incident_id" not in calls[0]
    assert calls[1]["p_incident_id"] == 9
    assert await store.search_evidence_items(None, 5, 0.0, None, None, None, None) == []


def test_evidence_embeddings_echo_the_source_video() -> None:
    embedder = MagicMock()
    embedder.is_configured.return_value = True
    embedder.embed = AsyncMock(return_value=[[0.1], [0.2]])
    app = FastAPI()
    app.include_router(create_incident_evidence_embeddings_router(embedder))
    with patch(
        "vss_agents.api.incident_evidence_embeddings.incident_db.get_db",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = TestClient(app).post(
            "/api/v1/incidents/evidence-embeddings",
            json={
                "evidence": [
                    {"item_type": "entity", "item_id": "E1", "item_name": "a", "video_id": "front.mp4"},
                    {"item_type": "entity", "item_id": "E1", "item_name": "b", "video_id": "rear.mp4"},
                ]
            },
        )
    assert resp.status_code == 200
    assert [(e["video_id"], e["item_id"]) for e in resp.json()] == [("front.mp4", "E1"), ("rear.mp4", "E1")]
