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

"""Unit tests for incident_report_gen: the incident contract's P1 -> RP1 calls and persistence."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest
from vss_agents import incident_contract
from vss_agents.incident_contract import IncidentExtractionError
from vss_agents.tools.incident_report_gen import IncidentReportGenConfig
from vss_agents.tools.incident_report_gen import IncidentReportGenInput
from vss_agents.tools.incident_report_gen import incident_report_gen
from vss_agents.tools.incident_report_gen import p1_request_body
from vss_agents.tools.incident_report_gen import persist_report
from vss_agents.tools.incident_report_gen import rp1_request_body
from vss_agents.tools.incident_report_gen import run_p1
from vss_agents.tools.incident_report_gen import run_rp1

MODEL_OUTPUT = {
    "incident": {
        "type": "burglary",
        "title": "Break-in at a shop",
        "start_timestamp": 1,
        "end_timestamp": 6,
        "description": "E1 forces the door open.",
        "severity_level": 2,
        "severity_reason": "Property damage only.",
        "confidence_score": None,
        "location": None,
    },
    "entities": [{"entity_id": "E1", "type": "human", "description": "Person in a hood."}],
    "instruments": [
        {"instrument_id": "I1", "entity_id": "E1", "name": "crowbar", "description": "Used on A1.", "threat_level": 3}
    ],
    "assets": [{"asset_id": "A1", "name": "door", "description": "Forced open."}],
    "timeline": [{"start_seconds": 1, "end_seconds": 6, "description": "E1 forces A1 with I1."}],
    "uncertainties": [],
}
VIDEO_URL = "https://r2.example/uploads/cam/clip.mp4?X-Amz-Signature=abc"


def _config() -> IncidentReportGenConfig:
    return IncidentReportGenConfig(
        vlm_base_url="https://switchyard.example",
        vlm_model_name="nvidia/cosmos-3-nano-reasoner",
        rp1_base_url="https://switchyard.example/",
    )


def _completion(content, finish_reason="stop") -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]})


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRequestBodies:
    def test_p1_sends_video_first_then_contract_prompt_with_strict_schema(self):
        body = p1_request_body("vlm", VIDEO_URL)
        parts = body["messages"][0]["content"]
        assert parts[0] == {"type": "video_url", "video_url": {"url": VIDEO_URL}}
        assert parts[1] == {"type": "text", "text": incident_contract.extraction_prompt()}
        assert body["response_format"] == incident_contract.response_format()
        assert body["max_tokens"] == 16384
        assert body["temperature"] == 0.0
        assert body["media_io_kwargs"] == {"video": {"num_frames": 64}}
        assert "data:video" not in json.dumps(body)

    def test_rp1_uses_contract_model_and_prompt(self):
        report = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))
        body = rp1_request_body(report)
        assert body["model"] == incident_contract.rp1_request()["model"]
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert '"duration": 5' in body["messages"][0]["content"]
        assert "response_format" not in body and "media_io_kwargs" not in body


class TestRunP1:
    @pytest.mark.asyncio
    async def test_valid_output_is_parsed_and_duration_derived(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return _completion(json.dumps(MODEL_OUTPUT))

        async with _client(handler) as client:
            report, raw = await run_p1(client, _config(), VIDEO_URL)
        assert seen["url"] == "https://switchyard.example/v1/chat/completions"
        assert report["incident"]["duration"] == 5
        assert raw == json.dumps(MODEL_OUTPUT)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        [
            json.dumps({**MODEL_OUTPUT, "incident": {**MODEL_OUTPUT["incident"], "type": "fighting"}}),
            "```json\n" + json.dumps(MODEL_OUTPUT) + "\n```",
            "",
        ],
    )
    async def test_contract_violation_raises_without_repair(self, content):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return _completion(content)

        async with _client(handler) as client:
            with pytest.raises(IncidentExtractionError):
                await run_p1(client, _config(), VIDEO_URL)
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_token_exhaustion_is_reported(self):
        async with _client(lambda _request: _completion("", finish_reason="length")) as client:
            with pytest.raises(IncidentExtractionError, match="finish_reason=length"):
                await run_p1(client, _config(), VIDEO_URL)

    @pytest.mark.asyncio
    async def test_http_error_is_not_a_contract_violation(self):
        async with _client(lambda _request: httpx.Response(500, text="boom")) as client:
            with pytest.raises(RuntimeError, match="HTTP 500"):
                await run_p1(client, _config(), VIDEO_URL)

    @pytest.mark.asyncio
    async def test_non_completion_body_is_an_error(self):
        async with _client(lambda _request: httpx.Response(200, content=b"null")) as client:
            with pytest.raises(ValueError, match="no completion"):
                await run_p1(client, _config(), VIDEO_URL)


class TestRunRP1:
    REPORT = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))

    @pytest.mark.asyncio
    async def test_returns_text(self):
        async with _client(lambda _request: _completion("  INCIDENT REPORT  ")) as client:
            assert await run_rp1(client, _config(), self.REPORT) == ("INCIDENT REPORT", None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("response", "error"),
        [
            (lambda _request: _completion(""), "no final content"),
            (lambda _request: httpx.Response(503, text="busy"), "HTTP 503"),
        ],
    )
    async def test_failures_never_raise(self, response, error):
        async with _client(response) as client:
            text, message = await run_rp1(client, _config(), self.REPORT)
        assert text is None and error in message


class TestPersistReport:
    REPORT = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))

    @pytest.mark.asyncio
    async def test_writes_contract_rows(self):
        db = AsyncMock()
        with (
            patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=True),
            patch("vss_agents.tools.incident_report_gen.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        ):
            await persist_report(incident_id="v1", model_run_id="run1", model_name="vlm", report=self.REPORT)
        db.insert_model_run.assert_awaited_once_with("run1", model_name="vlm", prompt_version="incident-contract-v2")
        fields = db.insert_incident.await_args.kwargs["fields"]
        assert fields == {
            "type": "burglary",
            "start_timestamp": "1",
            "end_timestamp": "6",
            "duration": 5,
            "description": "E1 forces the door open.",
            "severity_level": 2,
            "confidence_score": None,
        }
        db.add_incident_entity.assert_awaited_once_with(
            "v1", "run1", entity_id="E1", type="human", description="Person in a hood."
        )
        assert db.add_incident_instrument.await_args.kwargs["entity_id"] == "E1"
        assert db.add_incident_asset.await_args.kwargs["asset_id"] == "A1"
        db.upsert_video.assert_not_called()  # the console owns videos.filepath (the R2 key)

    @pytest.mark.asyncio
    async def test_db_failure_is_swallowed(self):
        db = AsyncMock()
        db.insert_incident.side_effect = RuntimeError("down")
        with (
            patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=True),
            patch("vss_agents.tools.incident_report_gen.incident_db.get_db", new_callable=AsyncMock, return_value=db),
        ):
            await persist_report(incident_id="v1", model_run_id="run1", model_name="vlm", report=self.REPORT)

    @pytest.mark.asyncio
    async def test_skips_when_db_not_configured(self):
        with patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=False):
            await persist_report(incident_id="v1", model_run_id="run1", model_name="vlm", report=self.REPORT)


class TestEndToEnd:
    """Drives the registered tool with the HTTP layer mocked."""

    async def _run(self, handler, *, tool_input=None):
        transport = httpx.MockTransport(handler)
        real_client = httpx.AsyncClient

        def client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real_client(*args, **kwargs)

        with (
            patch("vss_agents.tools.incident_report_gen.httpx.AsyncClient", side_effect=client_factory),
            patch("vss_agents.tools.incident_report_gen.persist_report", new_callable=AsyncMock) as persist,
            patch.dict("os.environ", {"OPENAI_API_KEY": "secret"}),
        ):
            async with incident_report_gen(_config(), MagicMock()) as function_info:
                result = await function_info.single_fn(
                    tool_input or IncidentReportGenInput(incident_id="v1", video_url=VIDEO_URL, model_run_id="run1")
                )
        return result, persist

    @pytest.mark.asyncio
    async def test_p1_then_rp1_then_persist(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = json.loads(request.content)
            return _completion(json.dumps(MODEL_OUTPUT) if "response_format" in body else "INCIDENT REPORT")

        result, persist = await self._run(handler)
        assert len(requests) == 2
        assert all(r.headers["authorization"] == "Bearer secret" for r in requests)
        assert result.report["incident"]["duration"] == 5
        assert result.report_text == "INCIDENT REPORT"
        assert result.contract_version == "incident-contract-v2"
        assert result.model == "nvidia/cosmos-3-nano-reasoner"
        persist.assert_awaited_once()
        assert persist.await_args.kwargs["model_run_id"] == "run1"

    @pytest.mark.asyncio
    async def test_contract_violation_persists_nothing(self):
        bad = {**MODEL_OUTPUT, "timeline": [{"start_seconds": 0, "end_seconds": None, "description": "lead-up"}]}
        with pytest.raises(IncidentExtractionError, match="outside"):
            await self._run(lambda _request: _completion(json.dumps(bad)))

    @pytest.mark.asyncio
    async def test_timeout_is_a_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with pytest.raises(TimeoutError):
            await self._run(handler)

    @pytest.mark.asyncio
    async def test_rp1_failure_keeps_the_report(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return _completion(json.dumps(MODEL_OUTPUT)) if "response_format" in body else httpx.Response(500, text="x")

        result, persist = await self._run(handler)
        assert result.report_text is None and "HTTP 500" in result.report_text_error
        persist.assert_awaited_once()
