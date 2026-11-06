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

"""The analysis time budget at its 540 s size: a slow main call still gets its report saved (7 Nov 2026).

On 7 Nov 00:43 SGT a 256 s main call used up the old 240 s budget, evidence started anyway, person tracking was
awaited for the clip's length, and the console gave up first. The report was lost. A fake clock stands in for the
slow call, so these tests take no real time.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from vss_agents.tools import incident_report_gen as module
from vss_agents.tools.incident_report_gen import ANALYSIS_BUDGET_ENV
from vss_agents.tools.incident_report_gen import DEFAULT_ANALYSIS_BUDGET_SECONDS
from vss_agents.tools.incident_report_gen import IncidentReportGenInput
from vss_agents.tools.incident_report_gen import analysis_budget_seconds
from vss_agents.tools.incident_report_gen import incident_report_gen
from vss_agents.utils import crop_evidence

from .test_incident_report_gen import MODEL_OUTPUT
from .test_incident_report_gen import VIDEO_URL
from .test_incident_report_gen import _completion
from .test_incident_report_gen import _config

CONSOLE_LIMIT_SECONDS = 600  # the console's own analysis limit


class _Clock:
    """A monotonic clock the slow P1 call moves forward."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _analyse(main_call_seconds: float, *, budget_env: str | None = None, tracking: bool = False):
    """Run the tool with a main call that takes ``main_call_seconds`` of (fake) time; returns result, persist, evidence mock."""
    clock = _Clock()

    def handler(request: httpx.Request) -> httpx.Response:
        if "response_format" in json.loads(request.content):
            clock.now += main_call_seconds
            return _completion(json.dumps(MODEL_OUTPUT))
        return _completion("INCIDENT REPORT")

    fake_time = SimpleNamespace(
        monotonic=clock, perf_counter=lambda: clock.now, time=lambda: 1.7e9, sleep=lambda _s: None
    )
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    env = {"OPENAI_API_KEY": "secret", "INCIDENT_TRACKING_ENABLED": "1" if tracking else "0"}
    if budget_env is not None:
        env[ANALYSIS_BUDGET_ENV] = budget_env
    with (
        patch.object(module, "time", fake_time),
        patch("vss_agents.tools.incident_report_gen.httpx.AsyncClient", side_effect=client_factory),
        patch(
            "vss_agents.tools.incident_report_gen.collect_evidence",
            new_callable=AsyncMock,
            return_value=[{"item_id": "E1", "image": "evidence/v1/b/E1.jpg", "image_gap": None}],
        ) as collect,
        patch(
            "vss_agents.tools.incident_report_gen.persist_revision", new_callable=AsyncMock, return_value=7
        ) as persist,
        patch.dict("os.environ", env),
    ):
        async with incident_report_gen(_config(), MagicMock()) as function_info:
            result = await function_info.single_fn(
                IncidentReportGenInput(
                    incident_id="v1", video_url=VIDEO_URL, model_run_id="run1", video_key="uploads/a.mp4", skip_rp1=True
                )
            )
    return result, persist, collect, clock


class TestBudgetSize:
    def test_the_default_is_540_seconds_leaving_the_console_a_minute_to_spare(self, monkeypatch) -> None:
        monkeypatch.delenv(ANALYSIS_BUDGET_ENV, raising=False)
        assert DEFAULT_ANALYSIS_BUDGET_SECONDS == 540.0 and analysis_budget_seconds() == 540.0
        assert CONSOLE_LIMIT_SECONDS - DEFAULT_ANALYSIS_BUDGET_SECONDS >= 60

    def test_the_env_var_still_overrides_it(self, monkeypatch) -> None:
        monkeypatch.setenv(ANALYSIS_BUDGET_ENV, "240")
        assert analysis_budget_seconds() == 240.0


class TestASlowMainCallStillSaves:
    @pytest.mark.asyncio
    async def test_a_256_second_main_call_under_the_old_240_second_budget_saves_without_evidence(self) -> None:
        result, persist, collect, _ = await _analyse(256, budget_env="240")
        collect.assert_not_awaited()  # the old code started the evidence step here and lost the report
        persist.assert_awaited_once()
        assert result.revision_id == 7
        saved = persist.await_args.kwargs["evidence"]
        assert saved and all(e["image"] is None for e in saved)
        assert all(e["image_gap"] == crop_evidence.TIME_BUDGET_GAP for e in saved)
        assert all(e["zoom_gap"] == crop_evidence.TIME_BUDGET_GAP for e in saved)

    @pytest.mark.asyncio
    async def test_a_main_call_that_spends_the_whole_540_second_budget_saves_without_evidence(self) -> None:
        result, persist, collect, clock = await _analyse(545)
        collect.assert_not_awaited()
        persist.assert_awaited_once()
        assert result.revision_id == 7
        assert all(e["image_gap"] == crop_evidence.TIME_BUDGET_GAP for e in persist.await_args.kwargs["evidence"])
        assert clock.now - 1000.0 < CONSOLE_LIMIT_SECONDS  # nothing ran after the main call

    @pytest.mark.asyncio
    async def test_the_skipped_stages_are_named_in_the_tracking_summaries(self) -> None:
        result, _, collect, _ = await _analyse(545, tracking=True)
        collect.assert_not_awaited()
        assert result.tracking["skipped"] == crop_evidence.TIME_BUDGET_GAP

    @pytest.mark.asyncio
    async def test_a_256_second_main_call_under_the_new_budget_still_runs_the_evidence_step_inside_the_budget(
        self,
    ) -> None:
        _, persist, collect, _ = await _analyse(256)
        collect.assert_awaited_once()
        deadline = collect.await_args.kwargs["deadline"]
        assert deadline == pytest.approx(1000.0 + DEFAULT_ANALYSIS_BUDGET_SECONDS)  # 284 s are left for it
        persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_fast_main_call_is_unchanged(self) -> None:
        result, persist, collect, _ = await _analyse(20)
        collect.assert_awaited_once()
        assert persist.await_args.kwargs["evidence"][0]["image"] == "evidence/v1/b/E1.jpg" and result.revision_id == 7
