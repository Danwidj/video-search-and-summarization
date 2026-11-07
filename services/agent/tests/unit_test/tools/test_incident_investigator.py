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

"""Unit tests for the investigator's read-only tools (a fake database)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from vss_agents.tools import incident_investigator
from vss_agents.utils import agent_loop

pytestmark = pytest.mark.asyncio

REVISIONS = [
    {"id": 10, "revision_no": 1, "kind": "ai", "created_at": "2026-11-01T01:00:00", "payload": {"title": "first"}},
    {"id": 11, "revision_no": 2, "kind": "human", "created_at": "2026-11-02T01:00:00", "payload": {"title": "second"}},
]


def _db(*, video="present", revisions=REVISIONS, official=None) -> MagicMock:
    db = MagicMock()
    db.get_video = AsyncMock(return_value=None if video is None else {"id": "V1", "official_revision_id": official})
    db.list_revisions = AsyncMock(return_value=revisions)
    db.get_revision = AsyncMock(side_effect=lambda rid: next((r for r in revisions if r["id"] == rid), None))
    return db


def _with_db(db):
    return patch.object(incident_investigator.incident_db, "get_db", AsyncMock(return_value=db))


async def test_read_report_prefers_the_official_version() -> None:
    with _with_db(_db(official=10)):
        text = await incident_investigator.read_report("V1")
    assert "version 1 (official)" in text
    assert '"first"' in text


async def test_read_report_falls_back_to_the_newest_version() -> None:
    with _with_db(_db()):
        text = await incident_investigator.read_report("V1")
    assert "version 2 (newest, not official)" in text


async def test_read_report_cuts_a_long_report() -> None:
    big = [{"id": 1, "revision_no": 1, "kind": "ai", "payload": {"summary": "x" * 20000}}]
    with _with_db(_db(revisions=big)):
        text = await incident_investigator.read_report("V1")
    assert text.endswith("...[report cut]")
    assert len(text) < incident_investigator.REPORT_CHARS + 200


@pytest.mark.parametrize("db", [_db(video=None), _db(revisions=[])])
async def test_a_missing_video_or_report_is_an_error_the_model_can_read(db) -> None:
    with _with_db(db), pytest.raises(ValueError):
        await incident_investigator.read_report("V1")


async def test_an_unreachable_database_is_not_a_value_error() -> None:
    with _with_db(None), pytest.raises(RuntimeError):
        await incident_investigator.read_report("V1")


async def test_list_versions_marks_the_official_one() -> None:
    with _with_db(_db(official=11)):
        rows = json.loads(await incident_investigator.list_versions("V1"))
    assert [(r["version"], r["made_by"], r["official"]) for r in rows] == [(1, "ai", False), (2, "human", True)]


async def test_the_tools_read_the_video_of_the_request_not_one_the_model_names() -> None:
    db = _db()
    with _with_db(db):

        async def ask() -> str:
            return await agent_loop.run_guarded_tool(
                "incident_read_report", {}, lambda: incident_investigator.read_report(agent_loop.current().video_id)
            )

        result = await agent_loop.run_loop(ask, "V9")
    assert result.status == "ok"
    db.get_video.assert_awaited_once_with("V9")
    assert result.steps[0]["args"] == {}
