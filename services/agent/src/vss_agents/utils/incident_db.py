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

"""Async Supabase PostgREST helper for CRUD against the incident-console schema.

The schema itself is owned by, and created by,
``deploy/docker/developer-profiles/dev-profile-incident/incident-console/db.py``
(module docstring there is the authoritative table list - do not redesign the
schema here, only mirror its tables/columns). That module also does the
``CREATE TABLE IF NOT EXISTS`` bootstrap on startup; this helper assumes the
schema already exists and only reads/writes rows.

Covers the tables an agent-side caller plausibly writes while generating and
persisting an incident report: ``videos``, ``model_runs``, ``incidents`` (plus
per-incident ``entities``/``instruments``/``assets`` evidence), ``reports``,
``review_status``, and ``notifications``. The human ground-truth (``gt_*``)
and similarity-match (``entity_matches``/``instrument_matches``/
``asset_matches``) tables are console/eval-workflow specific and are out of
scope for this helper.

Configuration is via two environment variables:
- ``INCIDENT_SUPABASE_URL`` — e.g. ``https://<project_ref>.supabase.co``
- ``INCIDENT_SUPABASE_SERVICE_ROLE_KEY`` — the ``service_role`` key (server-side
  only, same secret-handling rigor as the console's ``INCIDENT_DB_DSN`` password).

When either is unset, :func:`is_configured` returns ``False`` and
:func:`get_db` returns ``None`` - callers must treat the incident DB as an
optional feature and degrade gracefully, matching the console's own
"database not configured" stance. There is no fallback DSN.

Note: ``INCIDENT_DB_DSN`` is intentionally NOT used here — the console
(``incident-console/db.py``) continues to use that for its direct-Postgres
SQLAlchemy connection. The two config surfaces are independently maintained.

This module uses ``supabase-py``'s async client (``acreate_client``) rather than
``asyncpg``. The PostgREST layer does not support client-held transactions or
``SELECT ... FOR UPDATE`` row locking; see the plan doc's §2.2 for the
capability matrix. The one cross-table operation that needs atomicity
(``insert_incident``) calls a Postgres RPC function via ``/rpc/insert_incident``.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
from typing import Any

from supabase import AsyncClient
from supabase import acreate_client

logger = logging.getLogger(__name__)

_SUPABASE_URL_ENV_VAR = "INCIDENT_SUPABASE_URL"
_SUPABASE_KEY_ENV_VAR = "INCIDENT_SUPABASE_SERVICE_ROLE_KEY"


def _url_from_env() -> str:
    return (os.getenv(_SUPABASE_URL_ENV_VAR) or "").strip()


def _key_from_env() -> str:
    return (os.getenv(_SUPABASE_KEY_ENV_VAR) or "").strip()


def is_configured() -> bool:
    """Whether both Supabase URL and service role key are set."""
    return bool(_url_from_env() and _key_from_env())


def _utcnow() -> _dt.datetime:
    # The console schema uses PostgreSQL ``timestamp without time zone``.
    # Supabase/PostgREST also expects naive UTC for timestamptz-less columns.
    return _dt.datetime.now(_dt.UTC).replace(tzinfo=None)


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return row if row is not None else None


class IncidentDB:
    """Thin async CRUD wrapper around a Supabase async client."""

    def __init__(self, client: AsyncClient):
        self.client = client

    # -- lifecycle --------------------------------------------------------#
    @classmethod
    async def connect(
        cls,
        url: str | None = None,
        key: str | None = None,
    ) -> IncidentDB:
        """Create a client against ``url``/``key`` (default: env vars).

        Raises ``ValueError`` when credentials are missing — check
        :func:`is_configured` before calling so an unconfigured deployment
        degrades instead of crashing.
        """
        resolved_url = (url or _url_from_env()).strip()
        resolved_key = (key or _key_from_env()).strip()
        if not resolved_url or not resolved_key:
            raise ValueError(
                f"{_SUPABASE_URL_ENV_VAR} and {_SUPABASE_KEY_ENV_VAR} must be set; incident DB is not configured"
            )
        client = await acreate_client(resolved_url, resolved_key)
        return cls(client)

    async def close(self) -> None:
        # supabase-py async client has no explicit close; just drop the reference
        pass

    async def __aenter__(self) -> IncidentDB:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            # Use a lightweight head request to check connectivity
            await self.client.table("videos").select("id", count="exact", head=True).execute()  # type: ignore[arg-type]
            return True, "ok"
        except Exception as exc:
            return False, str(exc)

    # -- videos -------------------------------------------------------------#
    async def upsert_video(
        self,
        video_id: str,
        *,
        filepath: str | None = None,
        duration: int | None = None,
        source: str | None = None,
    ) -> str:
        """Insert or update the ``videos`` row for this id (the natural key)."""
        data = {
            "id": video_id,
            "filepath": filepath,
            "duration": duration,
            "source": source,
            "uploaded_datetime": _utcnow().isoformat(),
        }
        # PostgREST upsert via on_conflict
        await self.client.table("videos").upsert(data, on_conflict="id").execute()
        return video_id

    async def get_video(self, video_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        if for_update:
            # PostgREST has no SELECT ... FOR UPDATE equivalent. No production caller
            # uses this today (see plan §1.4), but we raise rather than silently ignore
            # so a future caller fails loudly instead of racing.
            raise NotImplementedError("for_update is not supported over PostgREST")
        result = await self.client.table("videos").select("*").eq("id", video_id).maybe_single().execute()
        return _row_to_dict(result.data)  # type: ignore[arg-type, union-attr]

    async def update_video(self, video_id: str, *, filepath: str | None) -> None:
        """Point an existing video row at its durable R2 object key."""
        await self.client.table("videos").update({"filepath": filepath}).eq("id", video_id).execute()

    async def list_videos(self) -> list[dict[str, Any]]:
        result = await self.client.table("videos").select("*").order("id").execute()
        return result.data or []  # type: ignore[return-value]

    async def delete_video(self, video_id: str) -> None:
        await self.client.table("videos").delete().eq("id", video_id).execute()

    # -- model_runs -----------------------------------------------------#
    async def insert_model_run(
        self,
        model_run_id: str,
        *,
        model_name: str,
        model_version: str | None = None,
        prompt_version: str | None = None,
        run_datetime: _dt.datetime | None = None,
        notes: str | None = None,
    ) -> str:
        """Insert or update-in-place - never delete-then-insert.

        Matches ``db.py``'s own ``insert_model_run`` note: ``incidents.model_run_id``
        cascades on delete, so re-registering an existing run id must not delete
        the incidents already recorded under it.
        """
        data = {
            "id": model_run_id,
            "model_name": model_name,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "run_datetime": (run_datetime or _utcnow()).isoformat(),
            "notes": notes,
        }
        await self.client.table("model_runs").upsert(data, on_conflict="id").execute()
        return model_run_id

    async def get_model_run(self, model_run_id: str) -> dict[str, Any] | None:
        result = await self.client.table("model_runs").select("*").eq("id", model_run_id).maybe_single().execute()
        return _row_to_dict(result.data)  # type: ignore[arg-type, union-attr]

    # -- incidents (model output) ----------------------------------------#
    _INCIDENT_FIELDS = (
        "type",
        "start_timestamp",
        "end_timestamp",
        "duration",
        "description",
        "severity_level",
        "confidence_score",
    )

    async def insert_incident(
        self, incident_id: str, model_run_id: str, *, fields: dict[str, Any] | None = None
    ) -> tuple[str, str]:
        """Insert-or-replace one model run's incident row for ``incident_id``.

        Calls the Postgres RPC function ``insert_incident`` which performs the
        delete-then-insert into ``incidents`` and resets ``review_status`` to
        ``unreviewed`` atomically in a single server-side transaction.
        """
        payload = {k: (fields or {}).get(k) for k in self._INCIDENT_FIELDS}
        # Call the RPC function - exact name and params to be confirmed from sibling task
        await self.client.rpc(  # type: ignore[misc]
            "insert_incident",
            {
                "p_incident_id": incident_id,
                "p_model_run_id": model_run_id,
                "p_type": payload["type"],
                "p_start_timestamp": payload["start_timestamp"],
                "p_end_timestamp": payload["end_timestamp"],
                "p_duration": payload["duration"],
                "p_description": payload["description"],
                "p_severity_level": payload["severity_level"],
                "p_confidence_score": payload["confidence_score"],
            },
        )
        return incident_id, model_run_id

    async def get_incident(self, incident_id: str, model_run_id: str) -> dict[str, Any] | None:
        result = await (
            self.client.table("incidents")
            .select("*")
            .eq("incident_id", incident_id)
            .eq("model_run_id", model_run_id)
            .maybe_single()
            .execute()
        )
        return _row_to_dict(result.data)  # type: ignore[arg-type, union-attr]

    async def list_incidents(self, *, model_run_id: str | None = None) -> list[dict[str, Any]]:
        query = self.client.table("incidents").select("*").order("incident_id")
        if model_run_id is not None:
            query = query.eq("model_run_id", model_run_id)
        result = await query.execute()
        return result.data or []  # type: ignore[return-value]

    async def update_incident(self, incident_id: str, model_run_id: str, *, fields: dict[str, Any]) -> None:
        allowed = {k: v for k, v in fields.items() if k in self._INCIDENT_FIELDS}
        if not allowed:
            return
        await (
            self.client.table("incidents")
            .update(allowed)
            .eq("incident_id", incident_id)
            .eq("model_run_id", model_run_id)
            .execute()
        )

    async def delete_incident(self, incident_id: str, model_run_id: str) -> None:
        await (
            self.client.table("incidents")
            .delete()
            .eq("incident_id", incident_id)
            .eq("model_run_id", model_run_id)
            .execute()
        )

    # -- entities / instruments / assets (model output evidence) --------- #
    async def add_incident_entity(
        self,
        incident_id: str,
        model_run_id: str,
        *,
        entity_id: str,
        type: str | None = None,
        description: str | None = None,
        image: str | None = None,
    ) -> None:
        data = {
            "incident_id": incident_id,
            "entity_id": entity_id,
            "model_run_id": model_run_id,
            "type": type,
            "description": description,
            "image": image,
        }
        await self.client.table("entities").insert(data).execute()

    async def delete_incident_entities(self, incident_id: str, model_run_id: str) -> None:
        """Delete this incident+run's person entities so a re-analysis starts clean.

        Mirrors :meth:`insert_incident`'s delete-then-insert semantics: entity
        ids are deterministic per (incident, person index), so re-inserting
        without deleting first would hit primary-key violations and keep stale
        person rows (the insert loop swallows per-entity failures by design).
        """
        await (
            self.client.table("entities")
            .delete()
            .eq("incident_id", incident_id)
            .eq("model_run_id", model_run_id)
            .execute()
        )

    # -- Deleted dead methods (no production callers per plan §1.3) -- #
    # set_review_status, list_* (incidents/entities/instruments/assets),
    # add_incident_instrument, add_incident_asset, insert_generated_report,
    # list_notifications, acknowledge_notification, transaction()
    # are intentionally not ported. If a future feature needs them, add them
    # with PostgREST-native implementations (likely via RPC functions).

    # Placeholder stubs that raise NotImplementedError to fail loudly if
    # something unexpectedly imports them — these can be removed once the
    # corresponding tests are deleted.
    async def set_review_status(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("set_review_status not ported to PostgREST (no production caller)")

    async def list_incident_entities(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("list_incident_entities not ported (no production caller)")

    async def list_incident_instruments(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("list_incident_instruments not ported (no production caller)")

    async def list_incident_assets(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("list_incident_assets not ported (no production caller)")

    async def add_incident_instrument(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("add_incident_instrument not ported (no production caller)")

    async def add_incident_asset(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("add_incident_asset not ported (no production caller)")

    async def insert_generated_report(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("insert_generated_report not ported (no production caller)")

    async def list_notifications(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("list_notifications not ported (no production caller)")

    async def acknowledge_notification(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("acknowledge_notification not ported (no production caller)")

    async def get_review_status(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("get_review_status not ported (no production caller)")


# --------------------------------------------------------------------------- #
# Module-level lazy singleton, mirroring db.py's own get_db()/reset_cache().
# --------------------------------------------------------------------------- #
_db: IncidentDB | None = None
_db_lock = asyncio.Lock()


async def get_db() -> IncidentDB | None:
    """Return the shared :class:`IncidentDB`, or ``None`` when unconfigured/unreachable.

    A missing ``INCIDENT_SUPABASE_URL``/``INCIDENT_SUPABASE_SERVICE_ROLE_KEY`` or a
    failed client creation is swallowed so callers can treat the incident DB as
    an optional feature, matching ``db.py``'s own "database not configured"
    degrade-gracefully contract.
    """
    global _db
    if _db is not None:
        return _db
    if not is_configured():
        return None
    async with _db_lock:
        if _db is not None:
            return _db  # type: ignore[unreachable]
        try:
            _db = await IncidentDB.connect()
        except Exception as exc:
            logger.warning("Incident DB unavailable: %s", exc)
            return None
    return _db


async def reset_cache() -> None:
    """Drop the cached client (used by tests)."""
    global _db
    if _db is not None:
        await _db.close()
    _db = None

