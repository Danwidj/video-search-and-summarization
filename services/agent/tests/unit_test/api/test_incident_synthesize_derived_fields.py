# SPDX-License-Identifier: Apache-2.0
"""Synthesise accepts analysis payloads exactly as /analyze returns and the database stores them."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vss_agents.api.incident_synthesize import VideoAnalysisInput
from vss_agents.api.incident_synthesize import create_incident_synthesize_router

from .test_incident_synthesize import _PAYLOAD_A


def _analyze_shaped(payload: dict) -> dict:
    """The payload with ``incident.duration`` added the way ``/analyze`` derives it."""
    shaped = copy.deepcopy(payload)
    incident = shaped["incident"]
    incident["duration"] = incident["end_timestamp"] - incident["start_timestamp"]
    return shaped


def _client() -> TestClient:
    embedder = MagicMock()
    embedder.is_configured.return_value = True
    embedder.embed_passage = AsyncMock(return_value=[0.1, 0.2])
    app = FastAPI()
    app.include_router(create_incident_synthesize_router(embedder=embedder))
    return TestClient(app)


def test_analyze_shaped_payload_with_duration_is_accepted():
    payload = _analyze_shaped(_PAYLOAD_A)
    assert payload["incident"]["duration"] == 25
    response = _client().post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam.mp4", "payload": payload}]},
    )
    assert response.status_code == 200
    assert "duration" not in response.json()["overview"]


def test_stored_payload_is_not_altered_by_validation():
    payload = _analyze_shaped(_PAYLOAD_A)
    before = copy.deepcopy(payload)
    video = VideoAnalysisInput(video_name="cam.mp4", payload=payload)
    assert video.payload == before
    assert video.payload["incident"]["duration"] == 25


def test_other_extra_incident_fields_are_still_rejected():
    payload = _analyze_shaped(_PAYLOAD_A)
    payload["incident"]["unknown_field"] = "x"
    response = _client().post(
        "/api/v1/incidents/synthesize",
        json={"videos": [{"video_name": "cam.mp4", "payload": payload}]},
    )
    assert response.status_code == 422
