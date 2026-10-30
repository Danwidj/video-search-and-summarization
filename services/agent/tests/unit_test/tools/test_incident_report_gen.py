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

"""Unit tests for incident_report_gen: the incident contract's P1 -> RP1 calls, evidence and the AI revision."""

from __future__ import annotations

import json
import logging
import math
from typing import ClassVar
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from vss_agents import incident_contract
from vss_agents.incident_contract import IncidentExtractionError
from vss_agents.tools.incident_report_gen import MAX_P1_OUTPUT_CHARS
from vss_agents.tools.incident_report_gen import MAX_REVIEWER_PROMPT_LENGTH
from vss_agents.tools.incident_report_gen import REVIEWER_PROMPT_PREAMBLE
from vss_agents.tools.incident_report_gen import IncidentReportGenConfig
from vss_agents.tools.incident_report_gen import IncidentReportGenInput
from vss_agents.tools.incident_report_gen import collect_evidence
from vss_agents.tools.incident_report_gen import incident_report_gen
from vss_agents.tools.incident_report_gen import normalize_reviewer_prompt
from vss_agents.tools.incident_report_gen import p1_request_body
from vss_agents.tools.incident_report_gen import persist_revision
from vss_agents.tools.incident_report_gen import resolve_video_length
from vss_agents.tools.incident_report_gen import revision_embedding
from vss_agents.tools.incident_report_gen import rp1_request_body
from vss_agents.tools.incident_report_gen import run_p1
from vss_agents.tools.incident_report_gen import run_rp1
from vss_agents.utils.crop_evidence import set_crop_evidence_service

from ..utils.test_video_duration import mp4
from ..utils.test_video_duration import range_server

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
    "entities": [
        {
            "entity_id": "E1",
            "type": "human",
            "description": "Person in a hood.",
            "timestamp_seconds": 2,
            "first_seen_seconds": 1,
            "last_seen_seconds": 4,
            "label": "person",
        }
    ],
    "instruments": [
        {
            "instrument_id": "I1",
            "entity_id": "E1",
            "name": "crowbar",
            "description": "Used on A1.",
            "threat_level": 3,
            "timestamp_seconds": 3,
            "label": "crowbar",
        }
    ],
    "assets": [
        {"asset_id": "A1", "name": "door", "description": "Forced open.", "timestamp_seconds": 2, "label": "door"}
    ],
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

    def test_p1_appends_the_framed_reviewer_prompt_after_the_contract_prompt(self):
        parts = p1_request_body("vlm", VIDEO_URL, "look at the door")["messages"][0]["content"]
        assert len(parts) == 3
        assert parts[1]["text"] == incident_contract.extraction_prompt()
        assert parts[2] == {"type": "text", "text": f"{REVIEWER_PROMPT_PREAMBLE}\n<<<\nlook at the door\n>>>"}

    def test_rp1_uses_contract_model_and_prompt(self):
        report = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))
        body = rp1_request_body(report)
        assert body["model"] == incident_contract.rp1_request()["model"]
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert '"duration": 5' in body["messages"][0]["content"]
        assert "response_format" not in body and "media_io_kwargs" not in body


class TestNormalizeReviewerPrompt:
    def test_blank_or_missing_is_none(self):
        assert normalize_reviewer_prompt(None) is None
        assert normalize_reviewer_prompt("  \x00 \n ") is None

    def test_strips_control_characters_and_normalises_newlines(self):
        assert normalize_reviewer_prompt(" a\x07b\r\nc ") == "ab\nc"

    def test_rejects_text_over_the_limit(self):
        assert normalize_reviewer_prompt("x" * MAX_REVIEWER_PROMPT_LENGTH) is not None
        with pytest.raises(ValueError, match="at most"):
            normalize_reviewer_prompt("x" * (MAX_REVIEWER_PROMPT_LENGTH + 1))


class TestRunP1:
    @pytest.mark.asyncio
    async def test_valid_output_is_parsed_and_duration_derived(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            return _completion(json.dumps(MODEL_OUTPUT))

        async with _client(handler) as client:
            report, raw, finish_reason = await run_p1(client, _config(), VIDEO_URL)
        assert seen["url"] == "https://switchyard.example/v1/chat/completions"
        assert report["incident"]["duration"] == 5
        assert raw == json.dumps(MODEL_OUTPUT)
        assert finish_reason == "stop"

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
            with pytest.raises(IncidentExtractionError) as excinfo:
                await run_p1(client, _config(), VIDEO_URL)
        assert len(calls) == 1
        assert excinfo.value.raw_output == content
        assert excinfo.value.finish_reason == "stop"
        assert excinfo.value.model == "nvidia/cosmos-3-nano-reasoner"

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


class TestCollectEvidence:
    REPORT = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))

    @pytest.mark.asyncio
    async def test_failure_becomes_an_image_gap_for_every_item(self):
        service = MagicMock()
        service.process_incident_report = AsyncMock(side_effect=RuntimeError("boom"))
        set_crop_evidence_service(service)
        try:
            entries = await collect_evidence(video_url=VIDEO_URL, incident_id="v1", report=self.REPORT)
        finally:
            set_crop_evidence_service(None)
        assert [entry["item_id"] for entry in entries] == ["E1", "I1", "A1"]
        assert all(entry["image"] is None and "boom" in entry["image_gap"] for entry in entries)


class TestPersistRevision:
    REPORT = incident_contract.parse_report(json.dumps(MODEL_OUTPUT))
    EVIDENCE: ClassVar[list[dict]] = [{"item_type": "entity", "item_id": "E1", "image": None, "image_gap": "no store"}]

    async def _persist(self, db, **overrides):
        kwargs = {
            "incident_id": "v1",
            "model_run_id": "run1",
            "model_name": "vlm",
            "report": self.REPORT,
            "evidence": self.EVIDENCE,
            "caller_owns_run": False,
        }
        with (
            patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=True),
            patch("vss_agents.tools.incident_report_gen.incident_db.get_db", new_callable=AsyncMock, return_value=db),
            patch(
                "vss_agents.tools.incident_report_gen.revision_embedding",
                new_callable=AsyncMock,
                return_value=[0.5] * 3,
            ),
        ):
            return await persist_revision(**{**kwargs, **overrides})

    @pytest.mark.asyncio
    async def test_registers_the_run_then_inserts_the_ai_revision(self):
        db = AsyncMock()
        db.insert_ai_revision.return_value = {"id": 9}
        assert await self._persist(db, note="Reviewer prompt: x") == 9
        db.insert_model_run.assert_awaited_once_with(
            "run1", model_name="vlm", prompt_version=incident_contract.contract_version()
        )
        db.insert_model_run_if_absent.assert_not_called()
        db.insert_ai_revision.assert_awaited_once_with(
            "v1",
            model_run_id="run1",
            payload=self.REPORT,
            evidence=self.EVIDENCE,
            note="Reviewer prompt: x",
            embedding=[0.5] * 3,
        )
        db.upsert_video.assert_not_called()  # the console owns videos.filepath (the R2 key)

    @pytest.mark.asyncio
    async def test_caller_owned_run_is_only_created_when_absent(self):
        db = AsyncMock()
        db.insert_ai_revision.return_value = {"id": 3}
        assert await self._persist(db, caller_owns_run=True) == 3
        db.insert_model_run_if_absent.assert_awaited_once_with(
            "run1", model_name="vlm", prompt_version=incident_contract.contract_version()
        )
        db.insert_model_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_failure_is_swallowed(self):
        db = AsyncMock()
        db.insert_ai_revision.side_effect = RuntimeError("down")
        assert await self._persist(db) is None

    @pytest.mark.asyncio
    async def test_skips_when_db_not_configured(self):
        with patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=False):
            result = await persist_revision(
                incident_id="v1",
                model_run_id="run1",
                model_name="vlm",
                report=self.REPORT,
                evidence=[],
                caller_owns_run=False,
            )
        assert result is None


class TestRevisionEmbedding:
    """The summary vector saved with an AI revision; a failure leaves the row with NULL."""

    REPORT: ClassVar[dict] = {"incident": {"title": "Fight", "description": "Two people fight."}}

    @pytest.mark.asyncio
    async def test_embeds_the_title_and_description_as_a_passage(self):
        embedder = MagicMock()
        embedder.is_configured.return_value = True
        embedder.embed_passage = AsyncMock(return_value=[0.1] * 1024)
        with patch("vss_agents.tools.incident_report_gen.RemoteTextEmbedder", return_value=embedder):
            assert await revision_embedding(self.REPORT) == [0.1] * 1024
        embedder.embed_passage.assert_awaited_once_with("Fight\nTwo people fight.")

    @pytest.mark.asyncio
    async def test_none_when_no_embedding_key_is_configured(self):
        embedder = MagicMock()
        embedder.is_configured.return_value = False
        with patch("vss_agents.tools.incident_report_gen.RemoteTextEmbedder", return_value=embedder):
            assert await revision_embedding(self.REPORT) is None
        embedder.embed_passage.assert_not_called()

    @pytest.mark.asyncio
    async def test_none_when_the_endpoint_fails(self):
        embedder = MagicMock()
        embedder.is_configured.return_value = True
        embedder.embed_passage = AsyncMock(side_effect=httpx.ConnectError("down"))
        with patch("vss_agents.tools.incident_report_gen.RemoteTextEmbedder", return_value=embedder):
            assert await revision_embedding(self.REPORT) is None

    @pytest.mark.asyncio
    async def test_none_for_a_report_without_text(self):
        embedder = MagicMock()
        embedder.is_configured.return_value = True
        with patch("vss_agents.tools.incident_report_gen.RemoteTextEmbedder", return_value=embedder):
            assert await revision_embedding({"incident": {}}) is None
        embedder.embed_passage.assert_not_called()


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
            patch(
                "vss_agents.tools.incident_report_gen.collect_evidence",
                new_callable=AsyncMock,
                return_value=[{"item_id": "E1", "image": "evidence/v1/b/E1.jpg", "image_gap": None}],
            ),
            patch(
                "vss_agents.tools.incident_report_gen.persist_revision", new_callable=AsyncMock, return_value=7
            ) as persist,
            patch.dict("os.environ", {"OPENAI_API_KEY": "secret"}),
        ):
            async with incident_report_gen(_config(), MagicMock()) as function_info:
                result = await function_info.single_fn(
                    tool_input or IncidentReportGenInput(incident_id="v1", video_url=VIDEO_URL, model_run_id="run1")
                )
        return result, persist

    @pytest.mark.asyncio
    async def test_p1_then_rp1_then_revision_for_a_caller_run_id(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = json.loads(request.content)
            return _completion(json.dumps(MODEL_OUTPUT) if "response_format" in body else "INCIDENT REPORT")

        result, persist = await self._run(handler)
        posts = [r for r in requests if r.method == "POST"]  # the GETs are the video-header read
        assert len(posts) == 2
        assert all(r.headers["authorization"] == "Bearer secret" for r in posts)
        assert result.report["incident"]["duration"] == 5
        assert result.report_text == "INCIDENT REPORT"
        assert result.contract_version == incident_contract.contract_version()
        assert result.model == "nvidia/cosmos-3-nano-reasoner"
        assert result.finish_reason == "stop"
        assert result.revision_id == 7
        assert result.evidence == [{"item_id": "E1", "image": "evidence/v1/b/E1.jpg", "image_gap": None}]
        kwargs = persist.await_args.kwargs
        assert kwargs["model_run_id"] == "run1" and kwargs["caller_owns_run"] is True
        assert kwargs["note"] is None  # the caller passed model_run_id, so it owns the run's notes

    @pytest.mark.asyncio
    async def test_skip_rp1_makes_only_the_p1_call(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return _completion(json.dumps(MODEL_OUTPUT))

        result, _ = await self._run(
            handler,
            tool_input=IncidentReportGenInput(
                incident_id="v1", video_url=VIDEO_URL, model_run_id="run1", skip_rp1=True
            ),
        )
        assert len(requests) == 1 and "response_format" in requests[0]
        assert result.report_text is None and result.report_text_error is None
        assert result.report["incident"]["duration"] == 5

    @pytest.mark.asyncio
    async def test_reviewer_prompt_and_model_reach_p1_and_the_revision_note(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append(body)
            return _completion(json.dumps(MODEL_OUTPUT) if "response_format" in body else "INCIDENT REPORT")

        model = incident_contract.allowed_models()[0]
        result, persist = await self._run(
            handler,
            tool_input=IncidentReportGenInput(
                incident_id="v1", video_url=VIDEO_URL, model=model, reviewer_prompt=" look at the door "
            ),
        )
        assert requests[0]["model"] == model and result.model == model
        assert requests[0]["messages"][0]["content"][2]["text"].endswith("<<<\nlook at the door\n>>>")
        assert persist.await_args.kwargs["note"] == "Reviewer prompt: look at the door"
        assert persist.await_args.kwargs["caller_owns_run"] is False

    @pytest.mark.asyncio
    async def test_model_outside_the_allowlist_is_rejected_before_any_call(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return _completion(json.dumps(MODEL_OUTPUT))

        with pytest.raises(ValueError, match="allowlist"):
            await self._run(
                handler, tool_input=IncidentReportGenInput(incident_id="v1", video_url=VIDEO_URL, model="not-a-model")
            )
        assert requests == []

    @pytest.mark.asyncio
    async def test_standalone_call_persists_under_the_configured_run_id(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return _completion(json.dumps(MODEL_OUTPUT) if "response_format" in body else "INCIDENT REPORT")

        _, persist = await self._run(handler, tool_input=IncidentReportGenInput(incident_id="v1", video_url=VIDEO_URL))
        persist.assert_awaited_once()
        assert persist.await_args.kwargs["model_run_id"] == "incident_report_gen"
        assert persist.await_args.kwargs["caller_owns_run"] is False

    @pytest.mark.asyncio
    async def test_timeline_outside_the_window_is_not_fatal(self):
        content = json.dumps(
            {**MODEL_OUTPUT, "timeline": [{"start_seconds": 0, "end_seconds": None, "description": "lead-up"}]}
        )

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return _completion(content if "response_format" in body else "INCIDENT REPORT")

        result, _ = await self._run(handler)
        assert result.raw_output == content
        assert result.report["timeline"] == [{"start_seconds": 0, "end_seconds": None, "description": "lead-up"}]

    @pytest.mark.asyncio
    async def test_core_violation_is_rejected_with_the_raw_output(self):
        content = json.dumps({**MODEL_OUTPUT, "incident": {**MODEL_OUTPUT["incident"], "end_timestamp": 0}})
        with pytest.raises(IncidentExtractionError, match="before start_timestamp") as excinfo:
            await self._run(lambda _request: _completion(content))
        assert excinfo.value.raw_output == content

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

        result, _ = await self._run(handler)
        assert result.report_text is None and "HTTP 500" in result.report_text_error
        assert result.report["incident"]["duration"] == 5


def _model_and_video_handler(content: str, video: httpx.Response | bytes, requests: list[httpx.Request] | None = None):
    """Completions for POSTs to the model endpoint; the object store (ranged GETs of ``video``) for GETs."""
    store = range_server(video) if isinstance(video, bytes) else (lambda _request: video)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if request.method == "GET":
            return store(request)
        body = json.loads(request.content)
        return _completion(content if "response_format" in body else "INCIDENT REPORT")

    return handler


class TestVideoBounds:
    """Known issue 1: the agent enforces WINDOW_BEYOND_VIDEO and TIMELINE_BEYOND_VIDEO itself."""

    _run = TestEndToEnd._run

    @pytest.mark.asyncio
    async def test_window_beyond_the_header_length_is_rejected_and_nothing_is_persisted(self):
        content = json.dumps(MODEL_OUTPUT)  # end_timestamp 6
        with pytest.raises(IncidentExtractionError, match="end_timestamp 6 is outside the 4 s video") as excinfo:
            await self._run(_model_and_video_handler(content, mp4(4.0)))
        assert excinfo.value.raw_output == content
        assert excinfo.value.model == "nvidia/cosmos-3-nano-reasoner"

    @pytest.mark.asyncio
    async def test_window_beyond_the_callers_length_is_rejected_without_reading_the_header(self):
        requests: list[httpx.Request] = []
        with pytest.raises(IncidentExtractionError, match="end_timestamp 6 is outside the 4 s video"):
            await self._run(
                _model_and_video_handler(json.dumps(MODEL_OUTPUT), mp4(30.0), requests),
                tool_input=IncidentReportGenInput(
                    incident_id="v1", video_url=VIDEO_URL, model_run_id="run1", video_duration_seconds=4.0
                ),
            )
        assert [r.method for r in requests] == ["POST"]

    @pytest.mark.asyncio
    async def test_the_last_partial_second_is_inside_the_video(self):
        # end_timestamp 6 names the second that starts at 6 s, which a 5.5 s video still has (0 <= T < length + 1).
        result, _ = await self._run(_model_and_video_handler(json.dumps(MODEL_OUTPUT), mp4(5.5)))
        assert result.video_bounds_checked is True and result.video_duration_seconds == 5.5

    @pytest.mark.asyncio
    async def test_a_window_inside_the_header_length_is_checked_and_recorded(self):
        result, persist = await self._run(_model_and_video_handler(json.dumps(MODEL_OUTPUT), mp4(30.0)))
        assert result.video_bounds_checked is True
        assert result.video_duration_seconds == 30.0
        assert result.video_duration_source == "mp4_header"
        assert result.video_bounds_unchecked_reason is None
        persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_the_callers_length_is_used_and_recorded(self):
        requests: list[httpx.Request] = []
        result, _ = await self._run(
            _model_and_video_handler(json.dumps(MODEL_OUTPUT), mp4(4.0), requests),
            tool_input=IncidentReportGenInput(
                incident_id="v1", video_url=VIDEO_URL, model_run_id="run1", video_duration_seconds=30
            ),
        )
        assert result.video_bounds_checked is True
        assert result.video_duration_seconds == 30.0 and result.video_duration_source == "request"
        assert all(r.method == "POST" for r in requests)

    @pytest.mark.asyncio
    async def test_timeline_beyond_the_video_is_recorded_enrichment_not_fatal(self):
        # The timeline is outside both the incident window and the 7 s video: enrichment codes only.
        content = json.dumps(
            {**MODEL_OUTPUT, "timeline": [{"start_seconds": 1, "end_seconds": 40, "description": "aftermath"}]}
        )
        result, _ = await self._run(_model_and_video_handler(content, mp4(7.0)))
        assert result.video_bounds_checked is True
        assert result.report["timeline"][0]["end_seconds"] == 40

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("video", "reason"),
        [
            (httpx.Response(403, text="SignatureDoesNotMatch"), "HTTP 403"),
            (httpx.Response(200, content=b"whole file"), "HTTP 200"),
            (b"not an mp4 file at all, just text", "not an MP4"),
        ],
    )
    async def test_an_unreadable_length_is_a_visible_unchecked_outcome(self, video, reason, caplog):
        with caplog.at_level(logging.WARNING, logger="vss_agents.tools.incident_report_gen"):
            result, persist = await self._run(_model_and_video_handler(json.dumps(MODEL_OUTPUT), video))
        assert result.video_bounds_checked is False
        assert result.video_duration_seconds is None and result.video_duration_source is None
        assert result.video_bounds_unchecked_reason.startswith("video length unknown: ")
        assert reason in result.video_bounds_unchecked_reason
        assert any("video-bounds rules not applied for v1" in r.getMessage() for r in caplog.records)
        persist.assert_awaited_once()  # same policy as the console and eval: an unknown length is not a failure

    @pytest.mark.asyncio
    async def test_the_model_key_never_reaches_the_object_store(self):
        requests: list[httpx.Request] = []
        await self._run(_model_and_video_handler(json.dumps(MODEL_OUTPUT), mp4(30.0), requests))
        gets = [r for r in requests if r.method == "GET"]
        posts = [r for r in requests if r.method == "POST"]
        assert gets and all("authorization" not in r.headers for r in gets)
        assert posts and all(r.headers["authorization"] == "Bearer secret" for r in posts)

    @pytest.mark.parametrize("value", [0, -1.5, math.nan, math.inf, True, "10"])
    def test_an_invalid_caller_length_is_rejected(self, value):
        with pytest.raises(ValueError, match="video_duration_seconds"):
            IncidentReportGenInput(incident_id="v1", video_url=VIDEO_URL, video_duration_seconds=value)

    @pytest.mark.asyncio
    async def test_resolve_rejects_an_invalid_length_passed_directly(self):
        with pytest.raises(ValueError, match="finite number above 0"):
            await resolve_video_length(VIDEO_URL, math.nan)


def _runaway(finish_reason: str | None = "length", chars: int = 10) -> IncidentExtractionError:
    return IncidentExtractionError(
        "content is not a single JSON document",
        raw_output="x" * chars,
        finish_reason=finish_reason,
        model="nvidia/cosmos-3-nano-reasoner",
    )


def _flaky_p1(monkeypatch: pytest.MonkeyPatch, failures: list[Exception]) -> list[int]:
    calls: list[int] = []

    async def fake_run_p1(client, config, video_url, **kwargs):
        calls.append(1)
        if failures:
            raise failures.pop(0)
        return incident_contract.parse_report(json.dumps(MODEL_OUTPUT)), json.dumps(MODEL_OUTPUT), "stop"

    monkeypatch.setattr("vss_agents.tools.incident_report_gen.run_p1", fake_run_p1)
    return calls


class TestP1Retry:
    """A runaway P1 output (cut off by length, or over the size limit) is retried once with the identical request."""

    INPUT = IncidentReportGenInput(incident_id="v1", video_url=VIDEO_URL, video_duration_seconds=30, skip_rp1=True)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failure", [_runaway("length"), _runaway("stop", MAX_P1_OUTPUT_CHARS + 1)])
    async def test_a_runaway_p1_output_is_retried_once_and_both_attempts_are_listed(self, monkeypatch, failure):
        calls = _flaky_p1(monkeypatch, [failure])
        result, _ = await TestEndToEnd()._run(lambda _request: _completion(""), tool_input=self.INPUT)
        assert len(calls) == 2
        assert [(a["attempt"], a["outcome"]) for a in result.p1_attempts] == [(1, "retried"), (2, "valid")]
        assert result.p1_attempts[1]["finish_reason"] == "stop"
        assert result.report["incident"]["duration"] == 5

    @pytest.mark.asyncio
    async def test_a_valid_first_output_lists_one_attempt(self, monkeypatch):
        calls = _flaky_p1(monkeypatch, [])
        result, _ = await TestEndToEnd()._run(lambda _request: _completion(""), tool_input=self.INPUT)
        assert len(calls) == 1
        assert [(a["attempt"], a["outcome"]) for a in result.p1_attempts] == [(1, "valid")]

    @pytest.mark.asyncio
    async def test_a_second_runaway_output_raises_with_both_attempts(self, monkeypatch):
        calls = _flaky_p1(monkeypatch, [_runaway(), _runaway()])
        with pytest.raises(IncidentExtractionError) as caught:
            await TestEndToEnd()._run(lambda _request: _completion(""), tool_input=self.INPUT)
        assert len(calls) == 2
        assert [a["outcome"] for a in caught.value.attempts] == ["retried", "failed"]
        assert caught.value.raw_output == "x" * 10  # the last rejected output, never repaired

    @pytest.mark.asyncio
    async def test_an_ordinary_contract_violation_is_not_retried(self, monkeypatch):
        calls = _flaky_p1(monkeypatch, [_runaway("stop", 500)])
        with pytest.raises(IncidentExtractionError) as caught:
            await TestEndToEnd()._run(lambda _request: _completion(""), tool_input=self.INPUT)
        assert len(calls) == 1
        assert [a["outcome"] for a in caught.value.attempts] == ["failed"]
