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

"""mvp3 behaviour of incident_report_gen: video-name addressing, readable run ids, stored analysis, R2 prefix."""

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from vss_agents import incident_contract
from vss_agents.tools.incident_report_gen import IncidentReportGenConfig
from vss_agents.tools.incident_report_gen import IncidentReportGenInput
from vss_agents.tools.incident_report_gen import collect_evidence
from vss_agents.tools.incident_report_gen import incident_report_gen
from vss_agents.tools.incident_report_gen import persist_analysis
from vss_agents.utils.crop_evidence import CropEvidenceService
from vss_agents.utils.crop_evidence import R2EvidenceStore
from vss_agents.utils.crop_evidence import set_crop_evidence_service

from .test_incident_report_gen import MODEL_OUTPUT
from .test_incident_report_gen import VIDEO_URL
from .test_incident_report_gen import _completion

VIDEO_NAME = "front door (night) 2026-10-30.mp4"
LONG_RUN_ID = f"{VIDEO_NAME}@2026-10-30T09:15:00.000Z"


def test_the_run_id_has_no_length_limit_and_the_video_is_addressed_by_name():
    tool_input = IncidentReportGenInput(video_name=VIDEO_NAME, video_url=VIDEO_URL, model_run_id=LONG_RUN_ID)
    assert tool_input.model_run_id == LONG_RUN_ID and len(LONG_RUN_ID) > 20
    assert "incident_id" not in IncidentReportGenInput.model_fields


@pytest.mark.asyncio
async def test_the_analysis_is_stored_under_the_video_name_and_no_revision_is_written():
    db = AsyncMock()
    db.insert_video_analysis.return_value = {"id": 4}
    report = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))
    with (
        patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=True),
        patch("vss_agents.tools.incident_report_gen.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        patch("vss_agents.tools.incident_report_gen.revision_embedding", new_callable=AsyncMock, return_value=None),
    ):
        analysis_id = await persist_analysis(
            video_name=VIDEO_NAME,
            model_run_id=LONG_RUN_ID,
            model_name="vlm",
            report=report,
            evidence=[],
            caller_owns_run=True,
        )
    assert analysis_id == 4
    db.insert_model_run_if_absent.assert_awaited_once()
    assert db.insert_video_analysis.await_args.args == (VIDEO_NAME,)
    assert db.insert_video_analysis.await_args.kwargs["model_run_id"] == LONG_RUN_ID
    assert [call[0] for call in db.method_calls if "revision" in call[0]] == []


async def _call_tool(tool_input: IncidentReportGenInput, db: AsyncMock | None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return _completion(json.dumps(MODEL_OUTPUT) if "response_format" in body else "INCIDENT REPORT")

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    config = IncidentReportGenConfig(
        vlm_base_url="http://vlm", vlm_model_name="nvidia/cosmos-3-nano-reasoner", rp1_base_url="http://rp1"
    )
    with (
        patch(
            "vss_agents.tools.incident_report_gen.httpx.AsyncClient",
            side_effect=lambda *a, **k: real_client(*a, **{**k, "transport": transport}),
        ),
        patch("vss_agents.tools.incident_report_gen.collect_evidence", new_callable=AsyncMock, return_value=[]),
        patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=db is not None),
        patch("vss_agents.tools.incident_report_gen.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        patch("vss_agents.tools.incident_report_gen.revision_embedding", new_callable=AsyncMock, return_value=None),
    ):
        async with incident_report_gen(config, MagicMock()) as function_info:
            return await function_info.single_fn(tool_input)


@pytest.mark.asyncio
async def test_a_call_without_a_run_id_reports_the_readable_run_it_registered():
    db = AsyncMock()
    db.insert_video_analysis.return_value = {"id": 8}
    result = await _call_tool(
        IncidentReportGenInput(video_name=VIDEO_NAME, video_url=VIDEO_URL, video_duration_seconds=30), db
    )
    assert (result.analysis_id, result.outcome) == (8, "stored")
    assert result.model_run_id is not None and result.model_run_id.startswith(f"{VIDEO_NAME}@")
    assert db.insert_model_run.await_args.args == (result.model_run_id,)


@pytest.mark.asyncio
async def test_the_caller_run_id_is_returned_as_given():
    db = AsyncMock()
    db.insert_video_analysis.return_value = {"id": 2}
    result = await _call_tool(
        IncidentReportGenInput(
            video_name=VIDEO_NAME, video_url=VIDEO_URL, model_run_id=LONG_RUN_ID, video_duration_seconds=30
        ),
        db,
    )
    assert result.model_run_id == LONG_RUN_ID and result.analysis_id == 2


@pytest.mark.asyncio
async def test_without_a_database_the_analysis_still_returns_with_outcome_not_stored():
    result = await _call_tool(
        IncidentReportGenInput(video_name=VIDEO_NAME, video_url=VIDEO_URL, video_duration_seconds=30), None
    )
    assert (result.analysis_id, result.model_run_id, result.outcome) == (None, None, "not_stored")
    assert result.report["incident"]["duration"] == 5


@pytest.mark.asyncio
async def test_crops_land_under_the_r2_prefix_and_the_stored_key_stays_prefix_free(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("R2_KEY_PREFIX", "mvp3/")
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [{}]
    store = R2EvidenceStore(bucket="bucket", client=client)
    service = CropEvidenceService(store=store)
    crop = MagicMock(image_bytes=b"jpg", normalized_box=[0.1, 0.1, 0.5, 0.5])
    service.crop_item = MagicMock(return_value=crop)  # type: ignore[method-assign]
    service.is_detector_available = MagicMock(return_value=True)  # type: ignore[method-assign]
    set_crop_evidence_service(service)
    try:
        entries = await collect_evidence(
            video_url=VIDEO_URL,
            video_name=VIDEO_NAME,
            report=incident_contract.parse_report(json.dumps(MODEL_OUTPUT)),
            video_key=f"uploads/{VIDEO_NAME}",
        )
    finally:
        set_crop_evidence_service(None)
    assert entries
    for entry in entries:
        assert entry["image"].startswith(f"evidence/uploads/{VIDEO_NAME}/run-1/")
    keys = {call.kwargs["Key"] for call in client.put_object.call_args_list}
    assert keys and all(key.startswith(f"mvp3/evidence/uploads/{VIDEO_NAME}/run-1/") for key in keys)
