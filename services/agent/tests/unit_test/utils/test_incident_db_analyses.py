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
"""Unit tests for the mvp3 parts of vss_agents.utils.incident_db against an in-memory fake PostgREST.

The fake keeps rows per table and honours ``eq``, ``order``, ``limit`` and ``maybe_single``, so these
tests check what the layer reads and writes rather than which mock methods were called.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest

from vss_agents.utils.incident_db import IncidentDB
from vss_agents.utils.incident_db import model_run_id


class _Query:
    def __init__(self, table: _Table):
        self._table = table
        self._op = "select"
        self._row: dict[str, Any] | None = None
        self._filters: list[tuple[str, Any]] = []
        self._orders: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._single = False
        self._conflict: str | None = None
        self._ignore_duplicates = False

    def select(self, *_columns: str, **_kwargs: Any) -> _Query:
        return self

    def insert(self, row: dict[str, Any]) -> _Query:
        self._op, self._row = "insert", row
        return self

    def upsert(self, row: dict[str, Any], *, on_conflict: str, ignore_duplicates: bool = False) -> _Query:
        self._op, self._row = "upsert", row
        self._conflict, self._ignore_duplicates = on_conflict, ignore_duplicates
        return self

    def eq(self, column: str, value: Any) -> _Query:
        self._filters.append((column, value))
        return self

    def order(self, column: str, *, desc: bool = False) -> _Query:
        self._orders.append((column, desc))
        return self

    def limit(self, count: int) -> _Query:
        self._limit = count
        return self

    def maybe_single(self) -> _Query:
        self._single = True
        return self

    async def execute(self) -> MagicMock:
        rows = self._table.rows
        if self._op == "insert":
            assert self._row is not None
            row = {"id": len(rows) + 1, **self._row}
            rows.append(row)
            return MagicMock(data=[dict(row)])
        if self._op == "upsert":
            assert self._row is not None and self._conflict is not None
            existing = next((r for r in rows if r[self._conflict] == self._row[self._conflict]), None)
            if existing is None:
                rows.append(dict(self._row))
            elif not self._ignore_duplicates:
                existing.update(self._row)
            return MagicMock(data=[])
        matched = [dict(r) for r in rows if all(r.get(c) == v for c, v in self._filters)]
        for column, desc in reversed(self._orders):
            matched.sort(key=lambda r, c=column: r[c], reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        if self._single:
            return MagicMock(data=matched[0] if matched else None)
        return MagicMock(data=matched)


class _Table:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []


class FakePostgrest:
    def __init__(self) -> None:
        self.tables: dict[str, _Table] = {}

    def table(self, name: str) -> _Query:
        return _Query(self.tables.setdefault(name, _Table()))

    def rows(self, name: str) -> list[dict[str, Any]]:
        return self.tables.setdefault(name, _Table()).rows


REPORT = {"incident": {"type": "fight", "severity_level": 3, "start_timestamp": 2.4, "end_timestamp": 9.0}}


@pytest.fixture
def fake() -> FakePostgrest:
    return FakePostgrest()


@pytest.fixture
def db(fake: FakePostgrest) -> IncidentDB:
    return IncidentDB(fake)  # type: ignore[arg-type]


def test_model_run_id_is_subject_at_utc_timestamp():
    when = _dt.datetime(2026, 10, 30, 9, 15, 0, 123000)
    assert model_run_id("front door.mp4", when) == "front door.mp4@2026-10-30T09:15:00.123Z"
    assert model_run_id("incident-4").startswith("incident-4@")


@pytest.mark.asyncio
async def test_readable_model_run_id_round_trips_through_model_runs(db: IncidentDB, fake: FakePostgrest):
    run_id = model_run_id("clip-2.mp4", _dt.datetime(2026, 10, 30, 1, 2, 3))
    assert await db.insert_model_run(run_id, model_name="vlm") == run_id
    assert (await db.get_model_run(run_id) or {})["id"] == run_id
    await db.insert_model_run(run_id, model_name="vlm-2")
    assert [r["model_name"] for r in fake.rows("model_runs")] == ["vlm-2"]


@pytest.mark.asyncio
async def test_insert_model_run_if_absent_keeps_the_existing_row(db: IncidentDB, fake: FakePostgrest):
    await db.insert_model_run("a.mp4@t", model_name="first", notes="console record")
    await db.insert_model_run_if_absent("a.mp4@t", model_name="second")
    assert fake.rows("model_runs")[0]["model_name"] == "first"
    assert fake.rows("model_runs")[0]["notes"] == "console record"


@pytest.mark.asyncio
async def test_insert_video_analysis_stores_payload_evidence_facets_and_embedding(db: IncidentDB, fake: FakePostgrest):
    row = await db.insert_video_analysis(
        "clip.mp4", model_run_id="clip.mp4@t", payload=REPORT, evidence=[{"item_id": "E1"}], embedding=[0.5]
    )
    stored = fake.rows("video_analyses")[0]
    assert row["id"] == 1 and stored["video_id"] == "clip.mp4" and stored["model_run_id"] == "clip.mp4@t"
    assert stored["payload"] is REPORT and stored["evidence"] == [{"item_id": "E1"}] and stored["embedding"] == [0.5]
    assert (stored["incident_type"], stored["severity_level"], stored["start_seconds"], stored["end_seconds"]) == (
        "fight",
        3,
        2,
        9,
    )
    assert "+" not in stored["created_at"]  # naive UTC
    assert not {"incident_id", "revision_no", "kind", "parent_id"} & stored.keys()


@pytest.mark.asyncio
async def test_insert_video_analysis_defaults_the_embedding_to_null(db: IncidentDB, fake: FakePostgrest):
    await db.insert_video_analysis("clip.mp4", model_run_id="r", payload=REPORT, evidence=[])
    assert fake.rows("video_analyses")[0]["embedding"] is None


@pytest.mark.asyncio
async def test_latest_analysis_wins_and_older_ones_stay(db: IncidentDB, fake: FakePostgrest):
    fake.rows("video_analyses").extend(
        [
            {"id": 1, "video_id": "a.mp4", "created_at": "2026-10-30T01:00:00", "model_run_id": "r1"},
            {"id": 3, "video_id": "a.mp4", "created_at": "2026-10-30T02:00:00", "model_run_id": "r3"},
            {"id": 2, "video_id": "a.mp4", "created_at": "2026-10-30T02:00:00", "model_run_id": "r2"},
            {"id": 4, "video_id": "b.mp4", "created_at": "2026-10-30T09:00:00", "model_run_id": "r4"},
        ]
    )
    latest = await db.get_latest_analysis("a.mp4")
    assert latest is not None and latest["id"] == 3
    assert [r["id"] for r in await db.list_analyses("a.mp4")] == [1, 2, 3]
    assert await db.get_latest_analysis("missing.mp4") is None
    assert await db.list_analyses("missing.mp4") == []


@pytest.mark.asyncio
async def test_list_videos_for_an_incident_only_returns_its_videos(db: IncidentDB, fake: FakePostgrest):
    fake.rows("videos").extend(
        [
            {"id": "b.mp4", "incident_id": 1},
            {"id": "a.mp4", "incident_id": 1},
            {"id": "c.mp4", "incident_id": 2},
        ]
    )
    assert [v["id"] for v in await db.list_videos(1)] == ["a.mp4", "b.mp4"]
    assert [v["id"] for v in await db.list_videos()] == ["a.mp4", "b.mp4", "c.mp4"]
    video = await db.get_video("c.mp4")
    assert video is not None and video["incident_id"] == 2


@pytest.mark.asyncio
async def test_get_incident_returns_the_row_or_none(db: IncidentDB, fake: FakePostgrest):
    fake.rows("incidents").append({"id": 5, "official_revision_id": 9})
    assert await db.get_incident(5) == {"id": 5, "official_revision_id": 9}
    assert await db.get_incident(6) is None


@pytest.mark.asyncio
async def test_list_revisions_reads_an_incidents_revisions_with_coverage_in_version_order(
    db: IncidentDB, fake: FakePostgrest
):
    fake.rows("report_revisions").extend(
        [
            {"id": 12, "incident_id": 1, "revision_no": 2, "video_names": ["a.mp4", "b.mp4"]},
            {"id": 11, "incident_id": 1, "revision_no": 1, "video_names": ["a.mp4"]},
            {"id": 13, "incident_id": 2, "revision_no": 1, "video_names": ["c.mp4"]},
        ]
    )
    revisions = await db.list_revisions(1)
    assert [(r["revision_no"], r["video_names"]) for r in revisions] == [(1, ["a.mp4"]), (2, ["a.mp4", "b.mp4"])]
    revision = await db.get_revision(13)
    assert revision is not None and revision["incident_id"] == 2


def test_the_layer_no_longer_writes_videos_or_revisions():
    for name in ("upsert_video", "update_video", "delete_video", "insert_ai_revision", "next_revision_no"):
        assert not hasattr(IncidentDB, name)


@pytest.mark.asyncio
async def test_writes_touch_only_model_runs_and_video_analyses(db: IncidentDB, fake: FakePostgrest):
    await db.insert_model_run("a.mp4@t", model_name="vlm")
    await db.insert_video_analysis("a.mp4", model_run_id="a.mp4@t", payload=REPORT, evidence=[])
    assert {name for name, table in fake.tables.items() if table.rows} == {"model_runs", "video_analyses"}


@pytest.mark.asyncio
async def test_search_revisions_still_calls_the_rpc():
    client = MagicMock()
    client.rpc.return_value.execute = AsyncMock(return_value=MagicMock(data=[{"revision_id": 4}]))
    assert await IncidentDB(client).search_revisions([0.1], top_k=2) == [{"revision_id": 4}]
