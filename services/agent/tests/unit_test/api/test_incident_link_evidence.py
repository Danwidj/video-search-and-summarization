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

"""Unit tests for ``POST /api/v1/incidents/link-evidence``."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from vss_agents.api.incident_link_evidence import VideoAnalysisInput
from vss_agents.api.incident_link_evidence import create_incident_link_evidence_router
from vss_agents.api.incident_link_evidence import validate_groups

_INCIDENT = {
    "type": "assault",
    "title": "Scuffle in a corridor",
    "start_timestamp": 1,
    "end_timestamp": 9,
    "description": "Two men argue near a dropped bag.",
    "severity_level": 2,
    "severity_reason": "Shoving observed.",
    "confidence_score": 0.8,
    "location": "Corridor",
}


def _payload(blue: str, white: str, bag: str) -> dict:
    return {
        "incident": _INCIDENT,
        "entities": [
            {
                "entity_id": "E1",
                "type": "human",
                "description": blue,
                "timestamp_seconds": 2,
                "first_seen_seconds": 1,
                "last_seen_seconds": 9,
                "label": "man in blue shirt",
            },
            {
                "entity_id": "E2",
                "type": "human",
                "description": white,
                "timestamp_seconds": 2,
                "first_seen_seconds": 1,
                "last_seen_seconds": 9,
                "label": "man in white shirt",
            },
        ],
        "instruments": [],
        "assets": [
            {"asset_id": "A1", "name": "plastic bag", "description": bag, "timestamp_seconds": 3, "label": "bag"}
        ],
        "timeline": [{"start_seconds": 1, "end_seconds": 9, "description": "Argument."}],
        "uncertainties": [],
    }


_A = _payload("Man in a blue shirt.", "Man in a white shirt.", "Crumpled white bag on the floor.")
_B = _payload("Blue-shirted man by the wall.", "White-shirted man pushing.", "White plastic bag on the floor.")
_VIDEOS = [
    VideoAnalysisInput(video_name="cam-a.mp4", payload=_A),
    VideoAnalysisInput(video_name="cam-b.mp4", payload=_B),
]
_BODY = {"videos": [{"video_name": "cam-a.mp4", "payload": _A}, {"video_name": "cam-b.mp4", "payload": _B}]}


def _members(*pairs: tuple[str, str]) -> list[dict]:
    return [{"video": video, "itemId": item_id} for video, item_id in pairs]


def _group(kind: str, *pairs: tuple[str, str], label: str = "Shared item", **extra) -> dict:
    return {"kind": kind, "label": label, "members": _members(*pairs), **extra}


def _client(rp1_base_url: str | None = "http://llm", api_key: str | None = "key") -> TestClient:
    app = FastAPI()
    app.include_router(create_incident_link_evidence_router(rp1_base_url=rp1_base_url, api_key=api_key))
    return TestClient(app)


def _post_with_llm(content: str | None = None, *, status: int = 200, error: Exception | None = None, body=_BODY):
    llm_resp = MagicMock(spec=httpx.Response)
    llm_resp.status_code = status
    llm_resp.text = "boom"
    llm_resp.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    with patch("vss_agents.api.incident_link_evidence.httpx.AsyncClient") as client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=llm_resp, side_effect=error)
        client_cls.return_value = mock_client
        response = _client().post("/api/v1/incidents/link-evidence", json=body)
    return response, mock_client


# ---------------------------------------------------------------------------
# validate_groups
# ---------------------------------------------------------------------------


def test_valid_groups_are_kept_and_renumbered():
    raw = [
        _group("entity", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E1"), label="Man in blue shirt", reason="Same shirt."),
        _group("asset", ("cam-a.mp4", "A1"), ("cam-b.mp4", "A1"), label="White bag"),
    ]
    groups = validate_groups(raw, _VIDEOS)
    assert [g.id for g in groups] == ["G1", "G2"]
    assert groups[0].kind == "entity"
    assert groups[0].source == "ai"
    assert groups[0].reason == "Same shirt."
    assert groups[1].reason is None
    assert [(m.video, m.itemId) for m in groups[0].members] == [("cam-a.mp4", "E1"), ("cam-b.mp4", "E1")]


def test_two_items_of_one_video_never_share_a_group():
    raw = [_group("entity", ("cam-a.mp4", "E1"), ("cam-a.mp4", "E2"), ("cam-b.mp4", "E1"))]
    assert validate_groups(raw, _VIDEOS) == []


def test_unknown_video_or_item_drops_the_group():
    assert validate_groups([_group("entity", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E9"))], _VIDEOS) == []
    assert validate_groups([_group("entity", ("cam-a.mp4", "E1"), ("cam-z.mp4", "E1"))], _VIDEOS) == []


def test_kind_must_match_the_item_kind():
    assert validate_groups([_group("asset", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E1"))], _VIDEOS) == []
    assert validate_groups([_group("person", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E1"))], _VIDEOS) == []


def test_a_member_is_in_at_most_one_group_and_single_member_groups_are_dropped():
    raw = [
        _group("entity", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E1")),
        _group("entity", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E2")),
        _group("entity", ("cam-a.mp4", "E2")),
    ]
    groups = validate_groups(raw, _VIDEOS)
    assert len(groups) == 1
    assert groups[0].id == "G1"


def test_malformed_groups_are_ignored():
    assert validate_groups("nope", _VIDEOS) == []
    assert (
        validate_groups([None, {"kind": "entity"}, {"kind": "entity", "label": "x", "members": [1, 2]}], _VIDEOS) == []
    )
    assert validate_groups([_group("entity", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E1"), label="  ")], _VIDEOS) == []


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


def test_links_groups_with_one_text_only_temperature_zero_call():
    content = json.dumps(
        {
            "groups": [
                _group("entity", ("cam-a.mp4", "E1"), ("cam-b.mp4", "E1"), label="Man in blue shirt"),
                _group("entity", ("cam-a.mp4", "E2"), ("cam-b.mp4", "E2"), label="Man in white shirt"),
                _group("asset", ("cam-a.mp4", "A1"), ("cam-b.mp4", "A1"), label="Plastic bag"),
            ]
        }
    )
    response, llm = _post_with_llm(content)
    assert response.status_code == 200
    groups = response.json()["evidence_groups"]
    assert [g["id"] for g in groups] == ["G1", "G2", "G3"]
    assert all(g["source"] == "ai" for g in groups)
    llm.post.assert_awaited_once()
    sent = llm.post.await_args.kwargs["json"]
    assert sent["temperature"] == 0.0
    prompt = sent["messages"][0]["content"]
    assert isinstance(prompt, str)
    assert "cam-a.mp4" in prompt
    assert "cam-b.mp4" in prompt
    assert "Crumpled white bag" in prompt


def test_fenced_json_is_accepted():
    content = (
        "```json\n" + json.dumps({"groups": [_group("asset", ("cam-a.mp4", "A1"), ("cam-b.mp4", "A1"))]}) + "\n```"
    )
    response, _ = _post_with_llm(content)
    assert [g["id"] for g in response.json()["evidence_groups"]] == ["G1"]


def test_one_video_makes_no_llm_call():
    body = {"videos": [{"video_name": "cam-a.mp4", "payload": _A}]}
    response, llm = _post_with_llm("{}", body=body)
    assert response.status_code == 200
    assert response.json() == {"evidence_groups": []}
    llm.post.assert_not_awaited()


def test_model_failures_and_invalid_output_give_an_empty_list():
    for content, kwargs in [
        ("not json", {}),
        ("[]", {}),
        ("", {}),
        (json.dumps({"groups": "x"}), {}),
        (None, {"status": 500}),
        (None, {"error": httpx.ConnectError("down")}),
    ]:
        response, _ = _post_with_llm(content, **kwargs)
        assert response.status_code == 200
        assert response.json() == {"evidence_groups": []}


def test_unconfigured_agent_is_503():
    for client in (_client(rp1_base_url=None), _client(api_key="")):
        assert client.post("/api/v1/incidents/link-evidence", json=_BODY).status_code == 503


def test_invalid_bodies_are_422():
    client = _client()
    assert client.post("/api/v1/incidents/link-evidence", json={"videos": []}).status_code == 422
    assert client.post("/api/v1/incidents/link-evidence", json={}).status_code == 422
    bad = {"videos": [{"video_name": "cam.mp4", "payload": {"incident": {"type": "burglary"}}}]}
    assert client.post("/api/v1/incidents/link-evidence", json=bad).status_code == 422
