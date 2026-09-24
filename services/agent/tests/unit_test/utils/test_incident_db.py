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

No live database is used: the Supabase async client is mocked throughout.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
import pytest_asyncio

from vss_agents.utils import incident_db
from vss_agents.utils.incident_db import IncidentDB


def _make_mock_client() -> MagicMock:
    """Create a mock Supabase async client with chainable query builder."""
    client = MagicMock()
    table_mock = MagicMock()

    # Chainable methods for select/upsert/update/delete
    select_mock = MagicMock()
    select_mock.eq = MagicMock(return_value=select_mock)
    select_mock.order = MagicMock(return_value=select_mock)
    select_mock.maybe_single = MagicMock(return_value=select_mock)
    select_mock.execute = AsyncMock(return_value=MagicMock(data=None))
    select_mock.head = True
    select_mock.count = "exact"

    upsert_mock = MagicMock()
    upsert_mock.on_conflict = MagicMock(return_value=upsert_mock)
    upsert_mock.execute = AsyncMock()

    update_mock = MagicMock()
    update_mock.eq = MagicMock(return_value=update_mock)
    update_mock.execute = AsyncMock()

    delete_mock = MagicMock()
    delete_mock.eq = MagicMock(return_value=delete_mock)
    delete_mock.execute = AsyncMock()

    insert_mock = MagicMock()
    insert_mock.execute = AsyncMock()

    rpc_builder = MagicMock()
    rpc_builder.execute = AsyncMock()
    rpc_mock = MagicMock(return_value=rpc_builder)

    table_mock.select = MagicMock(return_value=select_mock)
    table_mock.upsert = MagicMock(return_value=upsert_mock)
    table_mock.update = MagicMock(return_value=update_mock)
    table_mock.delete = MagicMock(return_value=delete_mock)
    table_mock.insert = MagicMock(return_value=insert_mock)

    client.table = MagicMock(return_value=table_mock)
    client.rpc = rpc_mock

    return client


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
    monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)


@pytest_asyncio.fixture(autouse=True)
async def _reset_singleton():
    await incident_db.reset_cache()
    yield
    await incident_db.reset_cache()


def test_is_configured_false_when_unset(monkeypatch):
    monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
    monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert incident_db.is_configured() is False


def test_is_configured_false_when_only_url(monkeypatch):
    monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert incident_db.is_configured() is False


def test_is_configured_false_when_only_key(monkeypatch):
    monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
    monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "secret-key")
    assert incident_db.is_configured() is False


def test_is_configured_true_when_both_set(monkeypatch):
    monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "secret-key")
    assert incident_db.is_configured() is True


@pytest.mark.asyncio
async def test_connect_raises_when_missing(monkeypatch):
    monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
    monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    with pytest.raises(ValueError, match="INCIDENT_SUPABASE_URL"):
        await IncidentDB.connect()


@pytest.mark.asyncio
async def test_connect_creates_client():
    mock_client = _make_mock_client()
    with patch("vss_agents.utils.incident_db.acreate_client", new=AsyncMock(return_value=mock_client)):
        db = await IncidentDB.connect(url="https://example.supabase.co", key="secret-key")
    assert db.client is mock_client


@pytest.mark.asyncio
async def test_connect_reads_from_env(monkeypatch):
    monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://from-env.supabase.co")
    monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "from-env-key")
    mock_client = _make_mock_client()
    mock_acreate = AsyncMock(return_value=mock_client)
    with patch("vss_agents.utils.incident_db.acreate_client", new=mock_acreate):
        await IncidentDB.connect()
        mock_acreate.assert_awaited_once_with("https://from-env.supabase.co", "from-env-key")


@pytest.mark.asyncio
async def test_close_is_noop():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.close()  # Should not raise


@pytest.mark.asyncio
async def test_async_context_manager():
    mock_client = _make_mock_client()
    async with IncidentDB(mock_client) as db:
        assert isinstance(db, IncidentDB)


@pytest.mark.asyncio
async def test_transaction_yields_a_writer_for_sequential_calls():
    """No real atomicity over PostgREST, but the async-with call shape must work
    (the mock backend's Analyze route groups several writes this way)."""
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    async with db.transaction() as tx:
        assert tx is db
        await tx.update_video("vid-1", filepath="r2/key.mp4")
    mock_client.table.assert_called_with("videos")


@pytest.mark.asyncio
async def test_healthcheck_ok():
    mock_client = _make_mock_client()
    mock_client.table().select().execute = AsyncMock(return_value=MagicMock(data=[{"id": "1"}]))
    db = IncidentDB(mock_client)
    ok, message = await db.healthcheck()
    assert ok is True
    assert message == "ok"


@pytest.mark.asyncio
async def test_healthcheck_failure_returns_message():
    mock_client = _make_mock_client()
    mock_client.table().select().execute = AsyncMock(side_effect=Exception("connection refused"))
    db = IncidentDB(mock_client)
    ok, message = await db.healthcheck()
    assert ok is False
    assert "connection refused" in message


@pytest.mark.asyncio
async def test_upsert_video_calls_upsert():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    result = await db.upsert_video("vid-1", filepath="a.mp4", duration=30, source="upload")
    assert result == "vid-1"
    # Verify upsert was called with correct data
    mock_client.table.assert_called_with("videos")
    upsert_call = mock_client.table().upsert
    upsert_call.assert_called_once()
    args, kwargs = upsert_call.call_args
    assert args[0]["id"] == "vid-1"
    assert args[0]["filepath"] == "a.mp4"
    assert args[0]["duration"] == 30
    assert args[0]["source"] == "upload"
    assert "uploaded_datetime" in args[0]
    assert kwargs["on_conflict"] == "id"


@pytest.mark.asyncio
async def test_get_video_returns_none_when_missing():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(return_value=MagicMock(data=None))
    db = IncidentDB(mock_client)
    assert await db.get_video("missing") is None


@pytest.mark.asyncio
async def test_get_video_returns_dict_when_found():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(
        return_value=MagicMock(data={"id": "vid-1", "filepath": "a.mp4"})
    )
    db = IncidentDB(mock_client)
    row = await db.get_video("vid-1")
    assert row == {"id": "vid-1", "filepath": "a.mp4"}


@pytest.mark.asyncio
async def test_get_video_for_update_raises_not_implemented():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    with pytest.raises(NotImplementedError, match="for_update is not supported"):
        await db.get_video("vid-1", for_update=True)


@pytest.mark.asyncio
async def test_list_videos_maps_all_rows():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(
        return_value=MagicMock(data=[{"id": "vid-1"}, {"id": "vid-2"}])
    )
    db = IncidentDB(mock_client)
    videos = await db.list_videos()
    assert [v["id"] for v in videos] == ["vid-1", "vid-2"]


@pytest.mark.asyncio
async def test_delete_video_calls_delete():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.delete_video("vid-1")
    mock_client.table.assert_called_with("videos")
    delete_call = mock_client.table().delete()
    delete_call.eq.assert_called_with("id", "vid-1")
    delete_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_video_calls_update():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.update_video("vid-1", filepath="r2/key.mp4")
    mock_client.table.assert_called_with("videos")
    update_call = mock_client.table().update({"filepath": "r2/key.mp4"})
    update_call.eq.assert_called_with("id", "vid-1")
    update_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_insert_model_run_upserts():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    result = await db.insert_model_run("run-1", model_name="m", model_version="v1")
    assert result == "run-1"
    mock_client.table.assert_called_with("model_runs")
    upsert_call = mock_client.table().upsert
    upsert_call.assert_called_once()
    args, kwargs = upsert_call.call_args
    assert args[0]["id"] == "run-1"
    assert args[0]["model_name"] == "m"
    assert args[0]["model_version"] == "v1"
    assert kwargs["on_conflict"] == "id"


@pytest.mark.asyncio
async def test_get_model_run_returns_none_when_missing():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(return_value=MagicMock(data=None))
    db = IncidentDB(mock_client)
    assert await db.get_model_run("missing") is None


@pytest.mark.asyncio
async def test_insert_incident_calls_rpc():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.insert_incident(
        "vid-1",
        "run-1",
        fields={"type": "burglary", "severity_level": 3, "confidence_score": 0.8},
    )
    mock_client.rpc.assert_called_once()
    args, _kwargs = mock_client.rpc.call_args
    assert args[0] == "insert_incident"
    assert args[1]["p_incident_id"] == "vid-1"
    assert args[1]["p_model_run_id"] == "run-1"
    assert args[1]["p_type"] == "burglary"
    assert args[1]["p_severity_level"] == 3
    assert args[1]["p_confidence_score"] == 0.8
    mock_client.rpc.return_value.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_incident_returns_none_when_missing():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(return_value=MagicMock(data=None))
    db = IncidentDB(mock_client)
    assert await db.get_incident("vid-1", "run-1") is None


@pytest.mark.asyncio
async def test_list_incidents_without_filter():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(return_value=MagicMock(data=[{"incident_id": "vid-1"}]))
    db = IncidentDB(mock_client)
    result = await db.list_incidents()
    assert result == [{"incident_id": "vid-1"}]


@pytest.mark.asyncio
async def test_list_incidents_with_model_run_filter():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(return_value=MagicMock(data=[{"incident_id": "vid-1"}]))
    db = IncidentDB(mock_client)
    await db.list_incidents(model_run_id="run-1")
    # Verify the eq filter was applied
    select_mock = mock_client.table().select()
    select_mock.eq.assert_called_with("model_run_id", "run-1")


@pytest.mark.asyncio
async def test_update_incident_with_no_allowed_fields_skips():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.update_incident("vid-1", "run-1", fields={"not_a_column": "x"})
    # update should not be called
    mock_client.table.assert_not_called()


@pytest.mark.asyncio
async def test_update_incident_builds_update():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.update_incident("vid-1", "run-1", fields={"severity_level": 5, "bogus": "x"})
    mock_client.table.assert_called_with("incidents")
    update_call = mock_client.table().update({"severity_level": 5})
    update_call.eq.assert_any_call("incident_id", "vid-1")
    update_call.eq.assert_any_call("model_run_id", "run-1")
    update_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_incident_calls_delete():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.delete_incident("vid-1", "run-1")
    mock_client.table.assert_called_with("incidents")
    delete_call = mock_client.table().delete()
    delete_call.eq.assert_any_call("incident_id", "vid-1")
    delete_call.eq.assert_any_call("model_run_id", "run-1")
    delete_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_incident_entity_inserts():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.add_incident_entity("vid-1", "run-1", entity_id="e1", type="human", description="a person")
    mock_client.table.assert_called_with("entities")
    insert_call = mock_client.table().insert
    insert_call.assert_called_once()
    args, _ = insert_call.call_args
    assert args[0]["incident_id"] == "vid-1"
    assert args[0]["entity_id"] == "e1"
    assert args[0]["model_run_id"] == "run-1"
    assert args[0]["type"] == "human"
    assert args[0]["description"] == "a person"


@pytest.mark.asyncio
async def test_add_incident_instrument_inserts():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.add_incident_instrument("vid-1", "run-1", instrument_id="i1", entity_id="e1", name="knife", threat_level=4)
    mock_client.table.assert_called_with("instruments")
    insert_call = mock_client.table().insert
    insert_call.assert_called_once()
    args, _ = insert_call.call_args
    assert args[0]["incident_id"] == "vid-1"
    assert args[0]["instrument_id"] == "i1"
    assert args[0]["model_run_id"] == "run-1"
    assert args[0]["entity_id"] == "e1"
    assert args[0]["name"] == "knife"
    assert args[0]["threat_level"] == 4


@pytest.mark.asyncio
async def test_add_incident_asset_inserts():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.add_incident_asset("vid-1", "run-1", asset_id="a1", name="car", description="a parked car")
    mock_client.table.assert_called_with("assets")
    insert_call = mock_client.table().insert
    insert_call.assert_called_once()
    args, _ = insert_call.call_args
    assert args[0]["incident_id"] == "vid-1"
    assert args[0]["asset_id"] == "a1"
    assert args[0]["model_run_id"] == "run-1"
    assert args[0]["name"] == "car"
    assert args[0]["description"] == "a parked car"


@pytest.mark.asyncio
async def test_delete_incident_entities_calls_delete():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.delete_incident_entities("vid-1", "run-1")
    mock_client.table.assert_called_with("entities")
    delete_call = mock_client.table().delete()
    delete_call.eq.assert_any_call("incident_id", "vid-1")
    delete_call.eq.assert_any_call("model_run_id", "run-1")
    delete_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_incident_instruments_calls_delete():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.delete_incident_instruments("vid-1", "run-1")
    mock_client.table.assert_called_with("instruments")
    delete_call = mock_client.table().delete()
    delete_call.eq.assert_any_call("incident_id", "vid-1")
    delete_call.eq.assert_any_call("model_run_id", "run-1")
    delete_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_incident_assets_calls_delete():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.delete_incident_assets("vid-1", "run-1")
    mock_client.table.assert_called_with("assets")
    delete_call = mock_client.table().delete()
    delete_call.eq.assert_any_call("incident_id", "vid-1")
    delete_call.eq.assert_any_call("model_run_id", "run-1")
    delete_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_incident_entities_scopes_by_incident_and_run():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(return_value=MagicMock(data=[{"entity_id": "e1"}]))
    db = IncidentDB(mock_client)
    result = await db.list_incident_entities("vid-1", "run-1")
    assert result == [{"entity_id": "e1"}]
    select_mock = mock_client.table().select()
    select_mock.eq.assert_any_call("incident_id", "vid-1")
    select_mock.eq.assert_any_call("model_run_id", "run-1")


@pytest.mark.asyncio
async def test_list_incident_instruments_without_model_run_filter():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(return_value=MagicMock(data=[{"instrument_id": "i1"}]))
    db = IncidentDB(mock_client)
    result = await db.list_incident_instruments("vid-1")
    assert result == [{"instrument_id": "i1"}]


@pytest.mark.asyncio
async def test_list_incident_assets_without_model_run_filter():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(return_value=MagicMock(data=[{"asset_id": "a1"}]))
    db = IncidentDB(mock_client)
    result = await db.list_incident_assets("vid-1")
    assert result == [{"asset_id": "a1"}]


@pytest.mark.asyncio
async def test_get_review_status_returns_none_when_missing():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(return_value=MagicMock(data=None))
    db = IncidentDB(mock_client)
    assert await db.get_review_status("vid-1", "run-1") is None


@pytest.mark.asyncio
async def test_set_review_status_rejects_invalid_status():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    with pytest.raises(ValueError, match="Invalid review status"):
        await db.set_review_status("vid-1", "run-1", status="bogus", reviewed_by="alice", notify_threshold=4)


@pytest.mark.asyncio
async def test_set_review_status_requires_reviewer_name():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    with pytest.raises(ValueError, match="Reviewer name is required"):
        await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="   ", notify_threshold=4)


@pytest.mark.asyncio
async def test_set_review_status_raises_when_incident_missing():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(return_value=MagicMock(data=None))
    db = IncidentDB(mock_client)
    with pytest.raises(ValueError, match="Incident not found"):
        await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)


@pytest.mark.asyncio
async def test_set_review_status_no_change_returns_early():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(
        side_effect=[
            MagicMock(data={"severity_level": 5}),
            MagicMock(data={"status": "verified"}),
        ]
    )
    db = IncidentDB(mock_client)
    result = await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)
    assert result == {"notified": False, "severity": 5}
    mock_client.table().update.assert_not_called()


@pytest.mark.asyncio
async def test_set_review_status_notifies_above_threshold():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(
        side_effect=[
            MagicMock(data={"severity_level": 5}),
            MagicMock(data=None),
        ]
    )
    db = IncidentDB(mock_client)
    result = await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)
    assert result == {"notified": True, "severity": 5}
    mock_client.table.assert_any_call("notifications")
    insert_call = mock_client.table().insert
    insert_call.assert_called_once()
    args, _ = insert_call.call_args
    assert args[0]["incident_id"] == "vid-1"
    assert args[0]["severity"] == 5


@pytest.mark.asyncio
async def test_set_review_status_below_threshold_does_not_notify():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(
        side_effect=[
            MagicMock(data={"severity_level": 2}),
            MagicMock(data=None),
        ]
    )
    db = IncidentDB(mock_client)
    result = await db.set_review_status("vid-1", "run-1", status="verified", reviewed_by="alice", notify_threshold=4)
    assert result == {"notified": False, "severity": 2}
    mock_client.table().insert.assert_not_called()


@pytest.mark.asyncio
async def test_list_notifications_filters_unacknowledged():
    mock_client = _make_mock_client()
    mock_client.table().select().order().execute = AsyncMock(
        return_value=MagicMock(data=[{"id": 1, "acknowledged": False}])
    )
    db = IncidentDB(mock_client)
    result = await db.list_notifications(only_unacknowledged=True)
    assert result == [{"id": 1, "acknowledged": False}]
    select_mock = mock_client.table().select()
    select_mock.eq.assert_called_with("acknowledged", False)


@pytest.mark.asyncio
async def test_acknowledge_notification_calls_update():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    await db.acknowledge_notification(42)
    mock_client.table.assert_called_with("notifications")
    update_call = mock_client.table().update({"acknowledged": True})
    update_call.eq.assert_called_with("id", 42)
    update_call.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_insert_generated_report_upserts():
    mock_client = _make_mock_client()
    db = IncidentDB(mock_client)
    result = await db.insert_generated_report(
        "report-1", incident_id="vid-1", model_run_id="run-1", filepath="reports/vid-1.md"
    )
    assert result == "report-1"
    mock_client.table.assert_called_with("reports")
    upsert_call = mock_client.table().upsert
    upsert_call.assert_called_once()
    args, kwargs = upsert_call.call_args
    assert args[0]["id"] == "report-1"
    assert args[0]["incident_id"] == "vid-1"
    assert args[0]["model_run_id"] == "run-1"
    assert args[0]["filepath"] == "reports/vid-1.md"
    assert kwargs["on_conflict"] == "id"


@pytest.mark.asyncio
async def test_get_generated_report_returns_none_when_missing():
    mock_client = _make_mock_client()
    mock_client.table().select().maybe_single().execute = AsyncMock(return_value=MagicMock(data=None))
    db = IncidentDB(mock_client)
    assert await db.get_generated_report("missing") is None


@pytest.mark.asyncio
async def test_get_db_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("INCIDENT_SUPABASE_URL", raising=False)
    monkeypatch.delenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert await incident_db.get_db() is None


@pytest.mark.asyncio
async def test_get_db_returns_none_on_connect_failure(monkeypatch):
    monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "secret")
    with patch.object(IncidentDB, "connect", new=AsyncMock(side_effect=OSError("unreachable"))):
        assert await incident_db.get_db() is None


@pytest.mark.asyncio
async def test_get_db_returns_and_caches_instance(monkeypatch):
    monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "secret")
    mock_client = _make_mock_client()
    with patch("vss_agents.utils.incident_db.acreate_client", new=AsyncMock(return_value=mock_client)):
        first = await incident_db.get_db()
        second = await incident_db.get_db()
    assert first is second
    assert isinstance(first, IncidentDB)


@pytest.mark.asyncio
async def test_get_db_concurrent_callers_do_not_race(monkeypatch):
    """Two coroutines racing on the lazy singleton must share one client, not leak a second."""
    monkeypatch.setenv("INCIDENT_SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY", "secret")

    async def _slow_create_client(**_kwargs):
        await asyncio.sleep(0.05)
        return _make_mock_client()

    with patch("vss_agents.utils.incident_db.acreate_client", new=AsyncMock(side_effect=_slow_create_client)):
        first, second = await asyncio.gather(incident_db.get_db(), incident_db.get_db())
    assert first is second


def test_utcnow_returns_naive_utc():
    """Timestamps must be naive UTC for PostgREST compatibility."""
    now = incident_db._utcnow()
    assert now.tzinfo is None
    assert abs(_dt.datetime.now(_dt.UTC).replace(tzinfo=None) - now) < _dt.timedelta(minutes=1)
