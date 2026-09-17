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
"""Unit tests for vss_agents.utils.incident_db.

No live database is used: the ``asyncpg`` pool/connection are mocked
throughout, per this module's own convention of pooling directly through
``asyncpg`` (not SQLAlchemy) against the schema owned by
``incident-console/db.py``.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import asyncpg
import pytest
import pytest_asyncio

from vss_agents.utils import incident_db
from vss_agents.utils.incident_db import DEFAULT_MAX_POOL_SIZE
from vss_agents.utils.incident_db import DEFAULT_MIN_POOL_SIZE
from vss_agents.utils.incident_db import IncidentDB


class _FakeAsyncCtx:
    """Minimal async context manager stand-in for asyncpg's pool/transaction contexts."""

    def __init__(self, value=None):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc_info):
        return False


def _make_mock_conn() -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=1)
    conn.transaction = MagicMock(return_value=_FakeAsyncCtx())
    return conn


def _make_mock_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_FakeAsyncCtx(conn))
    pool.close = AsyncMock()
    return pool


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("INCIDENT_DB_DSN", raising=False)


@pytest_asyncio.fixture(autouse=True)
async def _reset_singleton():
    await incident_db.reset_cache()
    yield
    await incident_db.reset_cache()


def test_is_configured_false_when_unset(monkeypatch):
    monkeypatch.delenv("INCIDENT_DB_DSN", raising=False)
    assert incident_db.is_configured() is False


def test_is_configured_true_when_set(monkeypatch):
    monkeypatch.setenv("INCIDENT_DB_DSN", "postgresql://user:pass@host/db")
    assert incident_db.is_configured() is True


@pytest.mark.asyncio
async def test_connect_raises_when_dsn_missing(monkeypatch):
    monkeypatch.delenv("INCIDENT_DB_DSN", raising=False)
    with pytest.raises(ValueError, match="INCIDENT_DB_DSN"):
        await IncidentDB.connect()


@pytest.mark.asyncio
async def test_connect_uses_small_pool_defaults():
    mock_pool = _make_mock_pool(_make_mock_conn())
    create_pool = AsyncMock(return_value=mock_pool)
    with patch("vss_agents.utils.incident_db.asyncpg.create_pool", new=create_pool):
        db = await IncidentDB.connect(dsn="postgresql://user:pass@host/db")
    assert db.pool is mock_pool
    create_pool.assert_awaited_once_with(
        dsn="postgresql://user:pass@host/db",
        min_size=DEFAULT_MIN_POOL_SIZE,
        max_size=DEFAULT_MAX_POOL_SIZE,
    )
    assert DEFAULT_MIN_POOL_SIZE == 1
    assert DEFAULT_MAX_POOL_SIZE == 2


@pytest.mark.asyncio
async def test_connect_reads_dsn_from_env(monkeypatch):
    monkeypatch.setenv("INCIDENT_DB_DSN", "postgresql://from-env/db")
    mock_pool = _make_mock_pool(_make_mock_conn())
    create_pool = AsyncMock(return_value=mock_pool)
    with patch("vss_agents.utils.incident_db.asyncpg.create_pool", new=create_pool):
        await IncidentDB.connect()
    create_pool.assert_awaited_once_with(
        dsn="postgresql://from-env/db", min_size=DEFAULT_MIN_POOL_SIZE, max_size=DEFAULT_MAX_POOL_SIZE
    )


@pytest.mark.asyncio
async def test_connect_honors_custom_pool_sizes():
    mock_pool = _make_mock_pool(_make_mock_conn())
    create_pool = AsyncMock(return_value=mock_pool)
    with patch("vss_agents.utils.incident_db.asyncpg.create_pool", new=create_pool):
        await IncidentDB.connect(dsn="postgresql://host/db", min_size=2, max_size=5)
    create_pool.assert_awaited_once_with(dsn="postgresql://host/db", min_size=2, max_size=5)


@pytest.mark.asyncio
async def test_close_closes_pool():
    mock_pool = _make_mock_pool(_make_mock_conn())
    db = IncidentDB(mock_pool)
    await db.close()
    mock_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_context_manager_closes_on_exit():
    mock_pool = _make_mock_pool(_make_mock_conn())
    async with IncidentDB(mock_pool) as db:
        assert isinstance(db, IncidentDB)
    mock_pool.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_healthcheck_ok():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    ok, message = await db.healthcheck()
    assert ok is True
    assert message == "ok"


@pytest.mark.asyncio
async def test_healthcheck_failure_returns_message():
    conn = _make_mock_conn()
    conn.fetchval = AsyncMock(side_effect=asyncpg.PostgresError("connection refused"))
    db = IncidentDB(_make_mock_pool(conn))
    ok, message = await db.healthcheck()
    assert ok is False
    assert "connection refused" in message


@pytest.mark.asyncio
async def test_upsert_video_issues_upsert_sql():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    result = await db.upsert_video("vid-1", filepath="a.mp4", duration=30, source="upload")
    assert result == "vid-1"
    conn.execute.assert_awaited_once()
    sql, *params = conn.execute.await_args.args
    assert "INSERT INTO videos" in sql
    assert "ON CONFLICT" in sql
    assert params[0] == "vid-1"
    assert params[1] == "a.mp4"
    assert params[2] == 30
    assert params[3] == "upload"


@pytest.mark.asyncio
async def test_get_video_returns_none_when_missing():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    assert await db.get_video("missing") is None


@pytest.mark.asyncio
async def test_get_video_returns_dict_when_found():
    conn = _make_mock_conn()
    conn.fetchrow = AsyncMock(return_value={"id": "vid-1", "filepath": "a.mp4"})
    db = IncidentDB(_make_mock_pool(conn))
    row = await db.get_video("vid-1")
    assert row == {"id": "vid-1", "filepath": "a.mp4"}


@pytest.mark.asyncio
async def test_list_videos_maps_all_rows():
    conn = _make_mock_conn()
    conn.fetch = AsyncMock(return_value=[{"id": "vid-1"}, {"id": "vid-2"}])
    db = IncidentDB(_make_mock_pool(conn))
    videos = await db.list_videos()
    assert [v["id"] for v in videos] == ["vid-1", "vid-2"]


@pytest.mark.asyncio
async def test_delete_video_issues_delete_sql():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.delete_video("vid-1")
    conn.execute.assert_awaited_once_with("DELETE FROM videos WHERE id = $1", "vid-1")


@pytest.mark.asyncio
async def test_insert_model_run_reregistration_updates_run_datetime():
    """Re-registering the same model_run_id must overwrite run_datetime, not keep the first value."""
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    first_run_datetime = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)
    second_run_datetime = _dt.datetime(2026, 6, 1, tzinfo=_dt.UTC)

    await db.insert_model_run("run-1", model_name="m", run_datetime=first_run_datetime)
    await db.insert_model_run("run-1", model_name="m", run_datetime=second_run_datetime)

    assert conn.execute.await_count == 2
    first_sql, second_sql = (call.args[0] for call in conn.execute.await_args_list)
    assert "run_datetime = EXCLUDED.run_datetime" in first_sql
    assert "run_datetime = EXCLUDED.run_datetime" in second_sql
    first_params, second_params = (call.args[1:] for call in conn.execute.await_args_list)
    assert first_params[4] == first_run_datetime
    assert second_params[4] == second_run_datetime
    assert second_params[4] != first_params[4]


@pytest.mark.asyncio
async def test_insert_incident_runs_inside_one_transaction_and_resets_review_status():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.insert_incident(
        "vid-1",
        "run-1",
        fields={"type": "burglary", "severity_level": 3, "confidence_score": 0.8},
    )
    conn.transaction.assert_called_once()
    assert conn.execute.await_count == 4
    statements = [call.args[0] for call in conn.execute.await_args_list]
    assert any("DELETE FROM incidents" in s for s in statements)
    assert any("INSERT INTO incidents" in s for s in statements)
    assert any("DELETE FROM review_status" in s for s in statements)
    assert any("INSERT INTO review_status" in s for s in statements)


@pytest.mark.asyncio
async def test_update_incident_with_no_allowed_fields_skips_query():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.update_incident("vid-1", "run-1", fields={"not_a_column": "x"})
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_incident_builds_set_clause_for_allowed_fields():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.update_incident("vid-1", "run-1", fields={"severity_level": 5, "bogus": "x"})
    conn.execute.assert_awaited_once()
    sql, *params = conn.execute.await_args.args
    assert "severity_level = $3" in sql
    assert params == ["vid-1", "run-1", 5]


@pytest.mark.asyncio
async def test_set_review_status_rejects_invalid_status():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    with pytest.raises(ValueError, match="Invalid review status"):
        await db.set_review_status("vid-1", "run-1", status="bogus", reviewed_by="alice", notify_threshold=4)


@pytest.mark.asyncio
async def test_set_review_status_requires_reviewer_name():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    with pytest.raises(ValueError, match="Reviewer name is required"):
        await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="   ", notify_threshold=4)


@pytest.mark.asyncio
async def test_set_review_status_raises_when_incident_missing():
    conn = _make_mock_conn()
    conn.fetchrow = AsyncMock(return_value=None)
    db = IncidentDB(_make_mock_pool(conn))
    with pytest.raises(ValueError, match="Incident not found"):
        await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)


@pytest.mark.asyncio
async def test_set_review_status_no_change_returns_early():
    conn = _make_mock_conn()
    conn.fetchrow = AsyncMock(side_effect=[{"severity_level": 5}, {"status": "verified"}])
    db = IncidentDB(_make_mock_pool(conn))
    result = await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)
    assert result == {"notified": False, "severity": 5}
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_review_status_notifies_above_threshold():
    conn = _make_mock_conn()
    conn.fetchrow = AsyncMock(side_effect=[{"severity_level": 5}, None])
    db = IncidentDB(_make_mock_pool(conn))
    result = await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)
    assert result == {"notified": True, "severity": 5}
    statements = [call.args[0] for call in conn.execute.await_args_list]
    assert any("INSERT INTO notifications" in s for s in statements)


@pytest.mark.asyncio
async def test_set_review_status_below_threshold_does_not_notify():
    conn = _make_mock_conn()
    conn.fetchrow = AsyncMock(side_effect=[{"severity_level": 2}, None])
    db = IncidentDB(_make_mock_pool(conn))
    result = await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)
    assert result == {"notified": False, "severity": 2}
    statements = [call.args[0] for call in conn.execute.await_args_list]
    assert not any("INSERT INTO notifications" in s for s in statements)


@pytest.mark.asyncio
async def test_add_incident_entity_inserts_row():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.add_incident_entity("vid-1", "run-1", entity_id="e1", type="human", description="a person")
    conn.execute.assert_awaited_once()
    sql, *params = conn.execute.await_args.args
    assert "INSERT INTO entities" in sql
    assert params == ["vid-1", "e1", "run-1", "human", "a person", None]


@pytest.mark.asyncio
async def test_list_notifications_filters_unacknowledged():
    conn = _make_mock_conn()
    conn.fetch = AsyncMock(return_value=[{"id": 1, "acknowledged": False}])
    db = IncidentDB(_make_mock_pool(conn))
    result = await db.list_notifications(only_unacknowledged=True)
    assert result == [{"id": 1, "acknowledged": False}]
    sql = conn.fetch.await_args.args[0]
    assert "WHERE acknowledged = FALSE" in sql


@pytest.mark.asyncio
async def test_acknowledge_notification_issues_update():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.acknowledge_notification(42)
    conn.execute.assert_awaited_once_with("UPDATE notifications SET acknowledged = TRUE WHERE id = $1", 42)


@pytest.mark.asyncio
async def test_insert_generated_report_deletes_then_inserts_in_one_transaction():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.insert_generated_report("report-1", incident_id="vid-1", model_run_id="run-1", filepath="reports/vid-1.md")
    conn.transaction.assert_called_once()
    assert conn.execute.await_count == 2
    statements = [call.args[0] for call in conn.execute.await_args_list]
    assert any("DELETE FROM reports" in s for s in statements)
    assert any("INSERT INTO reports" in s for s in statements)


@pytest.mark.asyncio
async def test_get_db_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("INCIDENT_DB_DSN", raising=False)
    assert await incident_db.get_db() is None


@pytest.mark.asyncio
async def test_get_db_returns_none_on_connect_failure(monkeypatch):
    monkeypatch.setenv("INCIDENT_DB_DSN", "postgresql://host/db")
    with patch.object(IncidentDB, "connect", new=AsyncMock(side_effect=OSError("unreachable"))):
        assert await incident_db.get_db() is None


@pytest.mark.asyncio
async def test_get_db_returns_and_caches_instance(monkeypatch):
    monkeypatch.setenv("INCIDENT_DB_DSN", "postgresql://host/db")
    mock_pool = _make_mock_pool(_make_mock_conn())
    create_pool = AsyncMock(return_value=mock_pool)
    with patch("vss_agents.utils.incident_db.asyncpg.create_pool", new=create_pool):
        first = await incident_db.get_db()
        second = await incident_db.get_db()
    assert first is second
    assert isinstance(first, IncidentDB)
    create_pool.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_video_issues_update_sql():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.update_video("vid-1", filepath="r2/key.mp4")
    conn.execute.assert_awaited_once_with("UPDATE videos SET filepath = $2 WHERE id = $1", "vid-1", "r2/key.mp4")


@pytest.mark.asyncio
async def test_transaction_binds_writer_to_single_connection():
    conn = _make_mock_conn()
    conn.fetchrow = AsyncMock(return_value={"id": "vid-1", "filepath": "r2/key.mp4"})
    db = IncidentDB(_make_mock_pool(conn))
    async with db.transaction() as tx:
        await tx.update_video("vid-1", filepath="r2/key.mp4")
        row = await tx.get_video("vid-1", for_update=True)
    conn.transaction.assert_called_once()
    conn.execute.assert_awaited_once_with("UPDATE videos SET filepath = $2 WHERE id = $1", "vid-1", "r2/key.mp4")
    assert row == {"id": "vid-1", "filepath": "r2/key.mp4"}
    sql = conn.fetchrow.await_args.args[0]
    assert sql.endswith("FOR UPDATE")


@pytest.mark.asyncio
async def test_get_video_for_update_requires_transaction():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    with pytest.raises(ValueError, match="for_update requires a transaction"):
        await db.get_video("vid-1", for_update=True)


@pytest.mark.asyncio
async def test_get_db_concurrent_callers_do_not_race_to_double_connect(monkeypatch):
    """Two coroutines racing on the lazy singleton must share one pool, not leak a second."""
    monkeypatch.setenv("INCIDENT_DB_DSN", "postgresql://host/db")

    async def _slow_create_pool(**_kwargs):
        await asyncio.sleep(0.05)
        return _make_mock_pool(_make_mock_conn())

    create_pool = AsyncMock(side_effect=_slow_create_pool)
    with patch("vss_agents.utils.incident_db.asyncpg.create_pool", new=create_pool):
        first, second = await asyncio.gather(incident_db.get_db(), incident_db.get_db())
    assert first is second
    create_pool.assert_awaited_once()


def test_utcnow_returns_naive_utc():
    """The console schema uses ``timestamp without time zone`` and asyncpg
    rejects tz-aware values for that type, so generated timestamps must be naive."""
    now = incident_db._utcnow()
    assert now.tzinfo is None
    assert abs(_dt.datetime.now(_dt.UTC).replace(tzinfo=None) - now) < _dt.timedelta(minutes=1)


@pytest.mark.asyncio
async def test_upsert_video_defaults_to_naive_uploaded_datetime():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.upsert_video("vid-1")
    _, *params = conn.execute.await_args.args
    assert params[4] is not None
    assert params[4].tzinfo is None


@pytest.mark.asyncio
async def test_insert_model_run_defaults_to_naive_run_datetime():
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.insert_model_run("run-1", model_name="m")
    _, *params = conn.execute.await_args.args
    assert params[4] is not None
    assert params[4].tzinfo is None


@pytest.mark.asyncio
async def test_delete_incident_entities_issues_scoped_delete():
    """Re-analysis deletes only this incident+run's entities before re-inserting."""
    conn = _make_mock_conn()
    db = IncidentDB(_make_mock_pool(conn))
    await db.delete_incident_entities("vid-1", "run-1")
    conn.execute.assert_awaited_once_with(
        "DELETE FROM entities WHERE incident_id = $1 AND model_run_id = $2", "vid-1", "run-1"
    )
