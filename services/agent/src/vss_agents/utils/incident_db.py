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

"""Async Supabase PostgREST helper for the agent's reads and writes against the incident schema.

The mvp3 schema is owned by ``deploy/docker/developer-profiles/dev-profile-incident/supabase/``
(see ``.docs/data.md``); this helper assumes it exists and only reads/writes rows. A video belongs to
one incident (``videos.incident_id``) and each analysis run of a video is one ``video_analyses`` row,
the latest row per video winning. The agent writes only ``model_runs`` and ``video_analyses`` (the
console owns incidents, videos, report revisions, the official pointer and ``evidence_crops``
writes); it reads videos, incidents and revisions. Search reads ``evidence_crops`` and writes
``queries`` and ``query_results`` through its own store (``api/incident_search.py``), using this client.

A model run id is readable text, ``<subject>@<UTC timestamp>`` (:func:`model_run_id`); the subject is
a video name, or ``incident-<id>`` for a synthesis run. ``video_analyses.payload`` holds the full
contract report of one video, ``evidence`` its evidence items and R2 image keys, and the plain facet
columns (``incident_type``, ``severity_level``, ``start_seconds``, ``end_seconds``) are filled by the
writer from the payload (:func:`revision_facets`).

Configuration is via two environment variables:
- ``INCIDENT_SUPABASE_URL`` — e.g. ``https://<project_ref>.supabase.co``
- ``INCIDENT_SUPABASE_SERVICE_ROLE_KEY`` — the ``service_role`` key (server-side
  only, same secret-handling rigor as the console's ``INCIDENT_DB_DSN`` password).

When either is unset, :func:`is_configured` returns ``False`` and
:func:`get_db` returns ``None`` - callers must treat the incident DB as an
optional feature and degrade gracefully, matching the console's own
"database not configured" stance. There is no fallback DSN.

This module uses ``supabase-py``'s async client (``acreate_client``) rather than
``asyncpg``. The PostgREST layer does not support client-held transactions or
``SELECT ... FOR UPDATE`` row locking; see ``.docs/data.md``'s "Client Access Models
& PostgREST/Direct-Postgres Split" section for why.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import datetime as _dt
import logging
import math
import os
from typing import TYPE_CHECKING
from typing import Any

from supabase import AsyncClient
from supabase import acreate_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

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


def model_run_id(subject: str, when: _dt.datetime | None = None) -> str:
    """Readable model run id ``<subject>@<UTC timestamp>``, e.g. ``clip.mp4@2026-10-30T09:15:00.000Z``.

    Same shape the console writes (``new Date().toISOString()``); ``subject`` is a video name, or
    ``incident-<id>`` for a synthesis run.
    """
    moment = when or _utcnow()
    return f"{subject}@{moment.isoformat(timespec='milliseconds')}Z"


def _row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return row if row is not None else None


class IncidentDB:
    """Thin async CRUD wrapper around a Supabase async client."""

    def __init__(self, client: AsyncClient):
        self.client = client

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[IncidentDB]:
        """Yield a writer for a sequence of calls sharing no real cross-call atomicity.

        PostgREST has no client-held transactions, so unlike the direct-Postgres
        version this does not roll back earlier calls if a later one in the
        block fails - it exists only so callers written against that sequential
        call-group shape (e.g. the mock backend's Analyze route) keep working.
        """
        yield self

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

    # -- incidents and videos (read only; the console owns them) -----------#
    async def get_incident(self, incident_id: int) -> dict[str, Any] | None:
        result = await self.client.table("incidents").select("*").eq("id", incident_id).maybe_single().execute()
        return _row_to_dict(result.data)  # type: ignore[arg-type, union-attr]

    async def get_video(self, video_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        if for_update:
            # PostgREST has no SELECT ... FOR UPDATE equivalent. No production caller
            # uses this today (see plan §1.4), but we raise rather than silently ignore
            # so a future caller fails loudly instead of racing.
            raise NotImplementedError("for_update is not supported over PostgREST")
        result = await self.client.table("videos").select("*").eq("id", video_id).maybe_single().execute()
        return _row_to_dict(result.data)  # type: ignore[arg-type, union-attr]

    async def list_videos(self, incident_id: int | None = None) -> list[dict[str, Any]]:
        """Every video by name, or only the videos of one incident."""
        query = self.client.table("videos").select("*")
        if incident_id is not None:
            query = query.eq("incident_id", incident_id)
        result = await query.order("id").execute()
        return result.data or []  # type: ignore[return-value]

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

        ``report_revisions.model_run_id`` references this row, so re-registering an
        existing run id must update it rather than delete it.
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

    async def insert_model_run_if_absent(
        self,
        model_run_id: str,
        *,
        model_name: str,
        prompt_version: str | None = None,
        run_datetime: _dt.datetime | None = None,
    ) -> str:
        """Create the ``model_runs`` row only when no row has this id; an existing row is left untouched.

        ``report_revisions.model_run_id`` is a foreign key, so an AI revision needs its run row first.
        In console agent mode the console writes the run's ``notes`` record after the agent returns;
        this placeholder (``notes`` NULL) never overwrites a row the console already wrote.
        """
        data = {
            "id": model_run_id,
            "model_name": model_name,
            "model_version": None,
            "prompt_version": prompt_version,
            "run_datetime": (run_datetime or _utcnow()).isoformat(),
            "notes": None,
        }
        await self.client.table("model_runs").upsert(data, on_conflict="id", ignore_duplicates=True).execute()
        return model_run_id

    # -- video_analyses (one row per analysis run; the latest row per video wins) ---#
    async def insert_video_analysis(
        self,
        video_id: str,
        *,
        model_run_id: str,
        payload: dict[str, Any],
        evidence: list[dict[str, Any]],
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        """Append an analysis of ``video_id`` and return the inserted row (with its ``id``).

        The facet columns are filled from ``payload`` (:func:`revision_facets`). ``embedding`` is the
        summary vector (:func:`revision_summary_text`); ``None`` stores NULL. The video and the run
        rows must exist first (foreign keys). Rows are never updated: a re-analysis is a new row.
        """
        row = {
            "video_id": video_id,
            "model_run_id": model_run_id,
            "payload": payload,
            "evidence": evidence,
            **revision_facets(payload),
            "embedding": embedding,
            "created_at": _utcnow().isoformat(),
        }
        result = await self.client.table("video_analyses").insert(row).execute()
        inserted = (result.data or [row])[0]
        return dict(inserted)  # type: ignore[arg-type]

    async def get_latest_analysis(self, video_id: str) -> dict[str, Any] | None:
        """The newest analysis of a video (``created_at`` then ``id`` descending), or ``None``."""
        result = await (
            self.client.table("video_analyses")
            .select("*")
            .eq("video_id", video_id)
            .order("created_at", desc=True)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return dict(rows[0]) if rows else None  # type: ignore[arg-type]

    async def list_analyses(self, video_id: str) -> list[dict[str, Any]]:
        """Every analysis of a video, oldest first."""
        result = await (
            self.client.table("video_analyses")
            .select("*")
            .eq("video_id", video_id)
            .order("created_at")
            .order("id")
            .execute()
        )
        return result.data or []  # type: ignore[return-value]

    # -- report_revisions (read only; the console appends them) ----------#
    async def get_revision(self, revision_id: int) -> dict[str, Any] | None:
        result = await self.client.table("report_revisions").select("*").eq("id", revision_id).maybe_single().execute()
        return _row_to_dict(result.data if result is not None else None)  # type: ignore[arg-type]

    async def list_revisions(self, incident_id: int) -> list[dict[str, Any]]:
        """An incident's revisions in version order; each row carries ``video_names`` (its coverage)."""
        result = await (
            self.client.table("report_revisions")
            .select("*")
            .eq("incident_id", incident_id)
            .order("revision_no")
            .execute()
        )
        return result.data or []  # type: ignore[return-value]

    async def search_revisions(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        min_similarity: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Cosine search over revision summary vectors (``search_report_revisions`` RPC), best first."""
        result = await self.client.rpc(
            "search_report_revisions",
            {"p_query_embedding": query_embedding, "p_top_k": top_k, "p_min_similarity": min_similarity},
        ).execute()
        return result.data or []  # type: ignore[return-value]


def _whole_seconds(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    seconds: float = value
    return round(seconds)


def revision_summary_text(payload: dict[str, Any]) -> str:
    """The text embedded for an analysis: ``incident.title`` then ``incident.description``.

    Missing parts are left out; an empty string means there is nothing to embed.
    """
    incident = payload.get("incident") if isinstance(payload, dict) else None
    if not isinstance(incident, dict):
        return ""
    parts = [incident.get("title"), incident.get("description")]
    return "\n".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def revision_facets(payload: dict[str, Any]) -> dict[str, Any]:
    """The plain facet columns of a ``video_analyses`` row, read from its contract ``payload``.

    ``incident_type`` and ``severity_level`` copy ``incident.type`` and ``incident.severity_level``;
    ``start_seconds`` and ``end_seconds`` are ``incident.start_timestamp`` and ``end_timestamp``
    rounded to whole seconds. A missing or malformed value leaves its column NULL.
    """
    incident = payload.get("incident") if isinstance(payload, dict) else None
    if not isinstance(incident, dict):
        incident = {}
    incident_type = incident.get("type")
    severity = incident.get("severity_level")
    return {
        "incident_type": incident_type if isinstance(incident_type, str) and incident_type else None,
        "severity_level": severity if isinstance(severity, int) and not isinstance(severity, bool) else None,
        "start_seconds": _whole_seconds(incident.get("start_timestamp")),
        "end_seconds": _whole_seconds(incident.get("end_timestamp")),
    }


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
        # mypy can't see that another coroutine may have set `_db` while this one
        # awaited the lock, so it treats the re-check as always-None from the
        # first guard above; it is reachable at runtime under real concurrency.
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
