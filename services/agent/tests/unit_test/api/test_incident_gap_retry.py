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

"""``POST`` and ``GET /api/v1/incidents/{video_id}/gap-retries``: the job that looks again for the items with no box."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vss_agents.api.incident_gap_retry import create_incident_gap_retry_router
from vss_agents.utils import crop_evidence
from vss_agents.utils import gap_retry_jobs

VIDEO = "video-1"
URL = f"/api/v1/incidents/{VIDEO}/gap-retries"
GAP_ENTRY = {
    "item_id": "A1",
    "item_type": "asset",
    "item_name": "crowbar",
    "label": "crowbar",
    "description": "Heavy metal tool.",
    "timestamp_seconds": 1,
    "image": None,
    "image_gap": "object not located at 1s or within 6s either side",
}
BOXED_ENTRY = {**GAP_ENTRY, "item_id": "A2", "image": "evidence/v/run-1/A2.jpg", "image_gap": None}


def _db(revisions: dict[int, dict[str, Any]], official: int | None = None, filepath: str = "videos/v.mp4") -> MagicMock:
    db = MagicMock()
    db.get_video = AsyncMock(return_value={"video_id": VIDEO, "filepath": filepath, "official_revision_id": official})
    db.get_revision = AsyncMock(side_effect=lambda rid: revisions.get(rid))
    db.list_revisions = AsyncMock(return_value=[revisions[rid] for rid in sorted(revisions)])
    return db


def _revision(rid: int, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": rid, "video_id": VIDEO, "revision_no": rid, "evidence": evidence}


def _service(found_for: set[str]) -> MagicMock:
    """A service whose retry finds a box for the items in ``found_for`` and nothing for the rest."""

    async def retry(*, video_ref: str, video_id: str, pending: list[Any], deadline: float) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for entry, _gap in pending:
            item_id = entry["item_id"]
            if item_id in found_for:
                found = crop_evidence.CropResult(
                    image_bytes=None,
                    normalized_box=[100, 200, 300, 400],
                    score=1.0,
                    frame_size=(10, 10),
                    box_seconds=4.0,
                )
                out[item_id] = crop_evidence.GapRetryOutcome(found)
            else:
                out[item_id] = crop_evidence.GapRetryOutcome(None, "no box was found near the second it is seen")
        return out

    service = MagicMock()
    service.retry_report_gaps = AsyncMock(side_effect=retry)
    return service


def _app(jobs: gap_retry_jobs.GapRetryJobs | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(create_incident_gap_retry_router(jobs or gap_retry_jobs.GapRetryJobs()))
    return app


def _poll(client: TestClient, job_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for _ in range(300):
        body = client.get(f"{URL}/{job_id}").json()
        if body["status"] == "done":
            return body
    raise AssertionError("the gap retry did not finish")


def test_the_database_must_be_configured() -> None:
    with patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=None):
        assert TestClient(_app()).post(URL, json={}).status_code == 503


def test_an_unknown_video_or_report_or_file_is_not_found() -> None:
    client = TestClient(_app())
    with patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=_db({})):
        assert client.post(URL, json={}).status_code == 404  # no report yet
    db = _db({1: _revision(1, [GAP_ENTRY])}, filepath="")
    with patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=db):
        assert client.post(URL, json={}).status_code == 404  # no stored file
    missing = MagicMock(get_video=AsyncMock(return_value=None))
    with patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=missing):
        assert client.post(URL, json={}).status_code == 404  # unknown video


def test_a_named_item_the_report_does_not_have_is_unprocessable() -> None:
    db = _db({1: _revision(1, [GAP_ENTRY])})
    with patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=db):
        response = TestClient(_app()).post(URL, json={"item_key": "A9"})
    assert response.status_code == 422
    assert "A9" in response.json()["detail"]


def test_a_retry_starts_at_once_and_reads_back_its_proposals() -> None:
    db = _db({1: _revision(1, [GAP_ENTRY, BOXED_ENTRY])}, official=1)
    service = _service(found_for={"A1"})
    with (
        patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        patch("vss_agents.api.incident_gap_retry.resolve_r2_url", return_value="https://signed.example/v.mp4"),
        patch("vss_agents.api.incident_gap_retry.crop_evidence.get_crop_evidence_service", return_value=service),
    ):
        with TestClient(_app()) as client:
            started = client.post(URL, json={})
            assert started.status_code == 202
            body = started.json()
            assert body["revision_id"] == 1
            assert [item["item_key"] for item in body["items"]] == ["A1"]  # the boxed item is not looked at
            done = _poll(client, body["job_id"])
    [item] = done["items"]
    assert item["status"] == "found"
    assert item["seconds"] == 4.0
    assert item["box"] == [100, 200, 300, 400]
    kwargs = service.retry_report_gaps.await_args.kwargs
    assert kwargs["video_id"] == VIDEO
    assert kwargs["video_ref"] == "https://signed.example/v.mp4"
    assert [entry["item_id"] for entry, _gap in kwargs["pending"]] == ["A1"]


def test_a_named_item_is_retried_alone_and_a_miss_is_reported_with_its_reason() -> None:
    db = _db({1: _revision(1, [GAP_ENTRY])}, official=1)
    service = _service(found_for=set())
    with (
        patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        patch("vss_agents.api.incident_gap_retry.resolve_r2_url", return_value="https://signed.example/v.mp4"),
        patch("vss_agents.api.incident_gap_retry.crop_evidence.get_crop_evidence_service", return_value=service),
    ):
        with TestClient(_app()) as client:
            body = client.post(URL, json={"item_key": "A1"}).json()
            done = _poll(client, body["job_id"])
    [item] = done["items"]
    assert item["status"] == "not_found"
    assert item["reason"] == crop_evidence.NO_BOX_REASON


def test_a_second_retry_while_one_runs_is_a_conflict_and_another_video_cannot_read_the_job() -> None:
    slow = MagicMock()

    async def sleepy(**_kwargs: Any) -> dict[str, Any]:
        await asyncio.sleep(30)
        return {}

    slow.retry_report_gaps = AsyncMock(side_effect=sleepy)
    db = _db({1: _revision(1, [GAP_ENTRY])}, official=1)
    with (
        patch("vss_agents.api.incident_gap_retry.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        patch("vss_agents.api.incident_gap_retry.resolve_r2_url", return_value="https://signed.example/v.mp4"),
        patch("vss_agents.api.incident_gap_retry.crop_evidence.get_crop_evidence_service", return_value=slow),
    ):
        with TestClient(_app()) as client:
            first = client.post(URL, json={})
            assert first.status_code == 202
            assert client.post(URL, json={}).status_code == 409
            job_id = first.json()["job_id"]
            assert client.get(f"/api/v1/incidents/other-video/gap-retries/{job_id}").status_code == 404
            assert client.get(f"{URL}/no-such-job").status_code == 404
