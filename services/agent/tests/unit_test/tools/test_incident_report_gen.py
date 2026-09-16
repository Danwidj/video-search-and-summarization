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
"""Unit tests for incident_report_gen.

No live VLM/LLM or database is used: the video_report_gen tool, the
extraction LLM, and incident_db are all mocked. Only the extraction LLM call
in ``TestEndToEnd`` is a candidate for a live check against a real endpoint
(see that class's docstring); everything else runs against fixture markdown.
"""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.data_models.incident_report import IncidentReport
from vss_agents.tools.incident_report_gen import IncidentReportGenConfig
from vss_agents.tools.incident_report_gen import IncidentReportGenInput
from vss_agents.tools.incident_report_gen import IncidentReportGenOutput
from vss_agents.tools.incident_report_gen import _derive_incident_bounds
from vss_agents.tools.incident_report_gen import _seconds_to_mmss
from vss_agents.tools.incident_report_gen import incident_report_gen
from vss_agents.tools.video_report_gen import VideoReportGenOutput

# Fixture markdown resembling video_report_gen's normalized output (see
# video_report_gen.py's _normalize_chunk_timestamps): absolute-time
# [Xs-Ys] markers, out of chronological order to exercise min/max derivation.
FIXTURE_REPORT_MARKDOWN = """# Video Analysis Report

## Analysis Results

[12.0s-18.5s] A person in a dark jacket forces open a side door.
[45.0s-50.0s] The same individual removes a cash box from the counter.
[5.0s-8.0s] A second person walks past the storefront without stopping.
"""


class TestSecondsToMmss:
    def test_under_a_minute(self):
        assert _seconds_to_mmss(7) == "0:07"

    def test_minutes_and_seconds(self):
        assert _seconds_to_mmss(125) == "2:05"

    def test_hours(self):
        assert _seconds_to_mmss(3725) == "1:02:05"

    def test_negative_clamped_to_zero(self):
        assert _seconds_to_mmss(-5) == "0:00"


class TestDeriveIncidentBounds:
    def test_no_content(self):
        assert _derive_incident_bounds(None) == ("0:00", "0:00", False)
        assert _derive_incident_bounds("") == ("0:00", "0:00", False)

    def test_no_timestamps_in_content(self):
        assert _derive_incident_bounds("No events detected.") == ("0:00", "0:00", False)

    def test_single_timestamp_range(self):
        assert _derive_incident_bounds("[10.0s-20.0s] Something happens.") == ("0:10", "0:20", True)

    def test_takes_min_start_and_max_end_across_out_of_order_chunks(self):
        start, end, confirmed = _derive_incident_bounds(FIXTURE_REPORT_MARKDOWN)
        assert start == "0:05"
        assert end == "0:50"
        assert confirmed is True


class TestIncidentReportGenConfig:
    def test_defaults(self):
        config = IncidentReportGenConfig(llm_name="nim_llm")
        assert config.video_report_tool == "video_report_gen"
        assert config.llm_name == "nim_llm"
        assert config.extraction_timeout_seconds == 60.0
        assert config.model_run_id == "incident_report_gen"
        assert config.model_name == "incident_report_gen"

    def test_requires_llm_name(self):
        with pytest.raises(Exception):
            IncidentReportGenConfig()


class TestIncidentReportGenOutput:
    def test_is_a_video_report_gen_output_subclass(self):
        """report_agent's _video_report_agent reads http_url/video_url/summary/etc.
        directly off whatever video_report_tool.ainvoke() returns; incident_report_gen
        must stay a drop-in replacement for video_report_gen at that call site."""
        assert issubclass(IncidentReportGenOutput, VideoReportGenOutput)

    def test_default_structured_report_is_a_fresh_incident_report(self):
        output = IncidentReportGenOutput()
        assert isinstance(output.structured_report, IncidentReport)
        assert output.structured_report.incident_type == "burglary"  # INCIDENT_TYPES[0]


class TestEndToEnd:
    """Drives the real, registered incident_report_gen() tool, mocking only the
    NAT builder boundary (video_report_gen tool + extraction LLM) and incident_db,
    so a regression in the orchestration/derivation/persistence wiring shows up
    here rather than only in a live integration run. Swap the mocked extraction
    LLM for one pointed at a real NGC endpoint if a live check is useful."""

    def _build_mocks(self, *, extracted: IncidentReport, db_configured: bool = False):
        config = IncidentReportGenConfig(llm_name="nim_llm")

        video_report_tool = MagicMock()
        video_report_tool.ainvoke = AsyncMock(
            return_value=VideoReportGenOutput(
                http_url="http://localhost:8000/static/vss_report_cam1_20250101_000000.md",
                video_url="http://localhost:8000/vst/clip.mp4",
                summary="A burglary occurred.",
                content=FIXTURE_REPORT_MARKDOWN,
                file_size=123,
            )
        )

        structured_llm = MagicMock()
        structured_llm.ainvoke = AsyncMock(return_value=extracted)
        llm = MagicMock()
        llm.with_structured_output = MagicMock(return_value=structured_llm)

        builder = MagicMock()
        builder.get_tool = AsyncMock(return_value=video_report_tool)
        builder.get_llm = AsyncMock(return_value=llm)

        return config, builder, video_report_tool

    async def _run(self, config, builder, *, db_configured: bool):
        with (
            patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=db_configured),
            patch("vss_agents.tools.incident_report_gen.incident_db.get_db", new_callable=AsyncMock) as mock_get_db,
        ):
            mock_db = AsyncMock()
            mock_get_db.return_value = mock_db if db_configured else None
            async with incident_report_gen(config, builder) as function_info:
                result = await function_info.single_fn(IncidentReportGenInput(sensor_id="cam1.mp4"))
            return result, mock_db

    @pytest.mark.asyncio
    async def test_derives_bounds_from_report_content_not_llm(self):
        """The extraction LLM is not trusted for incident_start/incident_end -
        they're always overwritten by the timestamp-chunk derivation."""
        extracted = IncidentReport(
            incident_type="burglary",
            severity=3,
            confidence=0.8,
            incident_start="9:99",  # LLM hallucination - must be overwritten
            incident_end="9:99",
            description="A burglary occurred.",
        )
        config, builder, video_report_tool = self._build_mocks(extracted=extracted)

        result, _ = await self._run(config, builder, db_configured=False)

        assert isinstance(result, IncidentReportGenOutput)
        assert result.structured_report.incident_type == "burglary"
        assert result.structured_report.incident_start == "0:05"
        assert result.structured_report.incident_end == "0:50"
        assert result.structured_report.incident_start_confirmed is True
        assert result.http_url == "http://localhost:8000/static/vss_report_cam1_20250101_000000.md"
        video_report_tool.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persists_to_incident_db_when_configured(self):
        extracted = IncidentReport(incident_type="fighting", severity=4, confidence=0.6)
        config, builder, _ = self._build_mocks(extracted=extracted)

        _, mock_db = await self._run(config, builder, db_configured=True)

        mock_db.upsert_video.assert_awaited_once()
        mock_db.insert_model_run.assert_awaited_once()
        mock_db.insert_incident.assert_awaited_once()
        _, kwargs = mock_db.insert_incident.await_args
        assert kwargs["fields"]["type"] == "fighting"
        assert kwargs["fields"]["severity_level"] == 4

    @pytest.mark.asyncio
    async def test_skips_persistence_when_db_not_configured(self):
        extracted = IncidentReport(incident_type="animal")
        config, builder, _ = self._build_mocks(extracted=extracted)

        result, mock_db = await self._run(config, builder, db_configured=False)

        assert isinstance(result, IncidentReportGenOutput)
        mock_db.upsert_video.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_db_failure_does_not_break_generation(self):
        """Fail-soft: a DB outage during persistence must not surface as a tool error."""
        extracted = IncidentReport(incident_type="explosion", severity=5, confidence=0.9)
        config, builder, _ = self._build_mocks(extracted=extracted)

        with (
            patch("vss_agents.tools.incident_report_gen.incident_db.is_configured", return_value=True),
            patch(
                "vss_agents.tools.incident_report_gen.incident_db.get_db",
                new_callable=AsyncMock,
                side_effect=RuntimeError("db unreachable"),
            ),
        ):
            async with incident_report_gen(config, builder) as function_info:
                result = await function_info.single_fn(IncidentReportGenInput(sensor_id="cam1.mp4"))

        assert isinstance(result, IncidentReportGenOutput)
        assert result.structured_report.incident_type == "explosion"
