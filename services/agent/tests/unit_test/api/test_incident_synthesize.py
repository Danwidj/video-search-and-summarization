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

"""Unit tests for ``POST /api/v1/incidents/synthesize``."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from vss_agents.api.incident_synthesize import _overview_from_incident
from vss_agents.api.incident_synthesize import _overview_text
from vss_agents.api.incident_synthesize import create_incident_synthesize_router

# ---------------------------------------------------------------------------
# Minimal contract-valid payloads
# ---------------------------------------------------------------------------

_INCIDENT_A = {
    "type": "burglary",
    "title": "Break-in at front entrance",
    "start_timestamp": 5,
    "end_timestamp": 30,
    "description": "A person broke in through the front door.",
    "severity_level": 3,
    "severity_reason": "Forced entry observed.",
    "confidence_score": 0.9,
    "location": "Front entrance",
}

_INCIDENT_B = {
    "type": "burglary",
    "title": "Intruder spotted at side window",
    "start_timestamp": 10,
    "end_timestamp": 45,
    "description": "Intruder entered via side window.",
    "severity_level": 4,
    "severity_reason": "Weapon visible in hand.",
    "confidence_score": 0.8,
    "location": "Side window",
}

_PAYLOAD_A: dict = {
    "incident": _INCIDENT_A,
    "entities": [
        {
            "entity_id": "E1",
            "type": "human",
            "description": "Hooded figure",
            "timestamp_seconds": 5,
            "first_seen_seconds": 5,
            "last_seen_seconds": 30,
            "label": "Suspect",
        }
    ],
    "instruments": [],
    "assets": [],
    "timeline": [{"start_seconds": 5, "end_seconds": 30, "description": "Break-in event."}],
    "uncertainties": [],
}

_PAYLOAD_B: dict = {
    "incident": _INCIDENT_B,
    "entities": [
        {
            "entity_id": "E1",
            "type": "human",
            "description": "Masked intruder",
            "timestamp_seconds": 10,
            "first_seen_seconds": 10,
            "last_seen_seconds": 45,
            "label": "Suspect",
        }
    ],
    "instruments": [],
    "assets": [],
    "timeline": [{"start_seconds": 10, "end_seconds": 45, "description": "Intruder visible."}],
    "uncertainties": [],
}

_EMBEDDING = [0.1] * 1024


def _embedder(*, configured: bool = True, error: Exception | None = None) -> MagicMock:
    emb = MagicMock()
    emb.is_configured.return_value = configured
    emb.embed_passage = AsyncMock(return_value=_EMBEDDING, side_effect=error)
    return emb


def _llm_response(overview: dict) -> httpx.Response:
    body = {"choices": [{"message": {"content": json.dumps(overview)}, "finish_reason": "stop"}]}
    return httpx.Response(200, json=body, request=httpx.Request("POST", "http://test/v1/chat/completions"))


def _client_one_video(embedder=None) -> TestClient:
    app = FastAPI()
    app.include_router(create_incident_synthesize_router(embedder=embedder))
    return TestClient(app)


def _client_multi_video(embedder=None, rp1_base_url="http://llm", api_key="key") -> TestClient:
    app = FastAPI()
    app.include_router(create_incident_synthesize_router(embedder=embedder, rp1_base_url=rp1_base_url, api_key=api_key))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def test_overview_from_incident_keeps_only_overview_fields():
    extra = {**_INCIDENT_A, "duration": 25, "unknown_field": "x"}
    result = _overview_from_incident(extra)
    assert "duration" not in result
    assert "unknown_field" not in result
    for field in ("type", "title", "description", "severity_level"):
        assert field in result


def test_overview_text_joins_title_and_description():
    overview = {"title": "A burglary", "description": "Someone broke in."}
    assert _overview_text(overview) == "A burglary Someone broke in."


def test_overview_text_handles_missing_fields():
    assert _overview_text({}) == ""
    assert _overview_text({"title": "Only a title"}) == "Only a title"


# ---------------------------------------------------------------------------
# Single-video pass-through
# ---------------------------------------------------------------------------


def test_single_video_overview_matches_analysis_incident_block():
    embedder = _embedder()
    client = _client_one_video(embedder)
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam-front.mp4", "payload": _PAYLOAD_A}]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["overview"]["type"] == _INCIDENT_A["type"]
    assert data["overview"]["title"] == _INCIDENT_A["title"]
    assert data["overview"]["severity_level"] == _INCIDENT_A["severity_level"]
    assert data["embedding"] == _EMBEDDING
    embedder.embed_passage.assert_awaited_once()


def test_single_video_overview_has_no_extra_fields():
    embedder = _embedder()
    client = _client_one_video(embedder)
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam.mp4", "payload": _PAYLOAD_A}]},
    )
    assert response.status_code == 200
    overview_keys = set(response.json()["overview"].keys())
    # duration is a derived field in the payload but NOT an incident block field
    assert "duration" not in overview_keys


# ---------------------------------------------------------------------------
# Multi-video synthesis via LLM
# ---------------------------------------------------------------------------


def test_multi_video_calls_llm_and_returns_synthesised_overview():
    merged_overview = {
        "type": "burglary",
        "title": "Multi-camera burglary event",
        "start_timestamp": 5,
        "end_timestamp": 45,
        "description": "Intruder observed at multiple entry points.",
        "severity_level": 4,
        "severity_reason": "Weapon visible in one camera.",
        "confidence_score": 0.85,
        "location": "Building perimeter",
    }
    llm_resp = MagicMock(spec=httpx.Response)
    llm_resp.status_code = 200
    llm_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(merged_overview)}, "finish_reason": "stop"}]
    }
    embedder = _embedder()
    client = _client_multi_video(embedder)
    with patch("vss_agents.api.incident_synthesize.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=llm_resp)
        mock_client_cls.return_value = mock_client
        response = client.post(
            "/api/v1/incidents/synthesize",
            json={
                "videos": [
                    {"video_name": "cam-front.mp4", "payload": _PAYLOAD_A},
                    {"video_name": "cam-side.mp4", "payload": _PAYLOAD_B},
                ]
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["overview"]["type"] == "burglary"
    assert data["overview"]["severity_level"] == 4
    assert data["embedding"] == _EMBEDDING


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_empty_videos_list_is_422():
    client = _client_one_video(_embedder())
    response = client.post("/api/v1/incidents/synthesize", json={"videos": []})
    assert response.status_code == 422


def test_invalid_payload_is_422():
    bad_payload = {"incident": {"type": "burglary"}}  # missing required fields
    client = _client_one_video(_embedder())
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam.mp4", "payload": bad_payload}]},
    )
    assert response.status_code == 422


def test_missing_videos_field_is_422():
    client = _client_one_video(_embedder())
    assert client.post("/api/v1/incidents/synthesize", json={}).status_code == 422


# ---------------------------------------------------------------------------
# Embedding failures
# ---------------------------------------------------------------------------


def test_unconfigured_embedder_is_503():
    client = _client_one_video(_embedder(configured=False))
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam.mp4", "payload": _PAYLOAD_A}]},
    )
    assert response.status_code == 503


def test_embedding_endpoint_error_is_502():
    client = _client_one_video(_embedder(error=httpx.ConnectError("down")))
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam.mp4", "payload": _PAYLOAD_A}]},
    )
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# Multi-video configuration errors
# ---------------------------------------------------------------------------


def test_multi_video_without_rp1_base_url_is_503():
    app = FastAPI()
    app.include_router(create_incident_synthesize_router(embedder=_embedder(), rp1_base_url=None, api_key="key"))
    client = TestClient(app)
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={
            "videos": [
                {"video_name": "cam-a.mp4", "payload": _PAYLOAD_A},
                {"video_name": "cam-b.mp4", "payload": _PAYLOAD_B},
            ]
        },
    )
    assert response.status_code == 503


def test_multi_video_without_api_key_is_503():
    app = FastAPI()
    app.include_router(create_incident_synthesize_router(embedder=_embedder(), rp1_base_url="http://llm", api_key=""))
    client = TestClient(app)
    response = client.post(
        "/api/v1/incidents/synthesize",
        json={
            "videos": [
                {"video_name": "cam-a.mp4", "payload": _PAYLOAD_A},
                {"video_name": "cam-b.mp4", "payload": _PAYLOAD_B},
            ]
        },
    )
    assert response.status_code == 503


def test_multi_video_llm_http_error_is_502():
    llm_resp = MagicMock(spec=httpx.Response)
    llm_resp.status_code = 500
    llm_resp.text = "Internal server error"
    llm_resp.request = httpx.Request("POST", "http://llm/v1/chat/completions")
    embedder = _embedder()
    client = _client_multi_video(embedder)
    with patch("vss_agents.api.incident_synthesize.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=llm_resp)
        mock_client_cls.return_value = mock_client
        response = client.post(
            "/api/v1/incidents/synthesize",
            json={
                "videos": [
                    {"video_name": "cam-a.mp4", "payload": _PAYLOAD_A},
                    {"video_name": "cam-b.mp4", "payload": _PAYLOAD_B},
                ]
            },
        )
    assert response.status_code == 502
