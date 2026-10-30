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

"""A video the VLM cannot decode (HTTP 200, null body) fails clearly, and the signed URL stays out of logs."""

import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from langchain_core.tools import StructuredTool
import pytest

from vss_agents.api.incident_analyze import register_incident_analyze_routes
from vss_agents.tools.incident_report_gen import IncidentReportGenInput
from vss_agents.tools.incident_report_gen import VlmNoAnswerError
from vss_agents.tools.incident_report_gen import redact_url
from vss_agents.tools.incident_report_gen import run_p1

from .test_incident_report_gen import VIDEO_URL
from .test_incident_report_gen import _client
from .test_incident_report_gen import _config

SIGNED_URL = "https://acct.r2.cloudflarestorage.com/bucket/uploads/clip.mp4?X-Amz-Signature=SECRETSIG&X-Amz-Expires=900"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"null", b'{"choices": []}', b"{}"])
async def test_a_null_or_choiceless_body_is_a_clear_no_answer_error(content):
    async with _client(lambda _request: httpx.Response(200, content=content)) as client:
        with pytest.raises(VlmNoAnswerError, match=r"returned no answer.*unsupported format.*10-bit") as caught:
            await run_p1(client, _config(), VIDEO_URL)
    assert isinstance(caught.value, ValueError)  # the pre-existing error type is kept


def _route_client(side_effect) -> TestClient:
    app = FastAPI()
    builder = MagicMock()
    tool = MagicMock()
    tool.ainvoke = AsyncMock(side_effect=side_effect)
    builder.get_tool = AsyncMock(return_value=tool)
    register_incident_analyze_routes(app, config=MagicMock(), builder=builder)
    return TestClient(app)


def test_analyze_answers_502_not_500_when_the_video_model_returns_no_answer():
    client = _route_client(VlmNoAnswerError("no completion in response body: None. The video model returned no answer"))
    response = client.post("/api/v1/incidents/v1/analyze", json={"video_url": VIDEO_URL})
    assert response.status_code == 502
    assert "returned no answer" in response.json()["detail"]


def test_redact_url_keeps_the_object_key_and_drops_the_signature():
    assert redact_url(SIGNED_URL) == "https://acct.r2.cloudflarestorage.com/bucket/uploads/clip.mp4"
    assert redact_url("https://user:pw@host.example:9000/a/b.mp4?x=1#f") == "https://host.example:9000/a/b.mp4"
    assert redact_url("not a url") == "<redacted url>"


def test_the_tool_input_never_prints_the_signed_url():
    tool_input = IncidentReportGenInput(video_name="clip.mp4", video_url=SIGNED_URL)
    for text in (repr(tool_input), str(tool_input), f"{tool_input}"):
        assert "SECRETSIG" not in text and "X-Amz" not in text
        assert "bucket/uploads/clip.mp4" in text
    assert tool_input.video_url == SIGNED_URL  # only the printed form is redacted


@pytest.mark.asyncio
async def test_a_failing_tool_call_never_logs_the_signed_url(caplog: pytest.LogCaptureFixture):
    # NAT logs a failed call's input as the plain kwargs dict LangChain passes to ``acall_invoke``.
    logger = logging.getLogger("nat.builder.function")

    async def failing_call(**kwargs: object) -> None:
        logger.error("Error with ainvoke in function with input: %s. Error: %s", kwargs, "boom")
        raise ValueError("boom")

    tool = StructuredTool.from_function(
        coroutine=failing_call, name="incident_report_gen", description="x", args_schema=IncidentReportGenInput
    )
    with caplog.at_level(logging.ERROR, logger="nat.builder.function"), pytest.raises(ValueError):
        await tool.ainvoke({"video_name": "clip.mp4", "video_url": SIGNED_URL})
    assert "bucket/uploads/clip.mp4" in caplog.text
    assert "SECRETSIG" not in caplog.text and "X-Amz-Signature" not in caplog.text
