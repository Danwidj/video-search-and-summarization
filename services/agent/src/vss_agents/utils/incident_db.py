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

"""Async Postgres helper for CRUD against the incident-console schema.

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

Configuration is a single DSN read from the ``INCIDENT_DB_DSN`` environment
variable. When it is unset, :func:`is_configured` returns ``False`` and
:func:`get_db` returns ``None`` - callers must treat the incident DB as an
optional feature and degrade gracefully, matching the console's own
"database not configured" stance. There is no fallback DSN.

Pooling: this module pools directly through ``asyncpg.create_pool`` (not
SQLAlchemy - its ``pool_size``/``max_overflow`` knobs don't apply to
``asyncpg``). Cloudflare Hyperdrive already pools connections in front of
Postgres, so the app-side pool is kept intentionally small - the module
default is ``min_size=1, max_size=2`` (see :data:`DEFAULT_MIN_POOL_SIZE` /
:data:`DEFAULT_MAX_POOL_SIZE`), overridable per call to :meth:`IncidentDB.connect`.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import datetime as _dt
import logging
import os
from typing import TYPE_CHECKING
from typing import Any

import asyncpg

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

_DSN_ENV_VAR = "INCIDENT_DB_DSN"

# Cloudflare Hyperdrive already pools in front of Postgres - keep the
# app-side asyncpg pool small rather than mirroring a typical
# directly-connected-app pool size.
DEFAULT_MIN_POOL_SIZE = 1
DEFAULT_MAX_POOL_SIZE = 2


def _dsn_from_env() -> str:
    return (os.getenv(_DSN_ENV_VAR) or "").strip()


def is_configured() -> bool:
    """Whether ``INCIDENT_DB_DSN`` is set. Mirrors ``db.py``'s own ``is_configured()``."""
    return bool(_dsn_from_env())


def _utcnow() -> _dt.datetime:
    # The console schema uses PostgreSQL ``timestamp without time zone``.
    # asyncpg rejects aware values for that type, so store UTC as a naive value
    # (matching SQLAlchemy's ``db.py`` default).
    return _dt.datetime.now(_dt.UTC).replace(tzinfo=None)


def _row_to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class IncidentDB:
    """Thin async CRUD wrapper around one ``asyncpg`` connection pool."""

    def __init__(self, pool: asyncpg.Pool, *, connection: asyncpg.Connection | None = None):
        self.pool = pool
        self._connection = connection

    @asynccontextmanager
    async def _acquire(self) -> AsyncIterator[asyncpg.Connection]:
        if self._connection is not None:
            yield self._connection
        else:
            async with self.pool.acquire() as conn:
                yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[IncidentDB]:
        """Yield a writer bound to one transaction; use it only inside this context.

        All CRUD calls on the yielded writer share the connection. Existing
        method-level transactions become savepoints, so a later failure rolls
        back the entire operation (including its incident/review status).
        """
        async with self._acquire() as conn, conn.transaction():
            yield IncidentDB(self.pool, connection=conn)

    # -- lifecycle --------------------------------------------------------#
    @classmethod
    async def connect(
        cls,
        dsn: str | None = None,
        *,
        min_size: int = DEFAULT_MIN_POOL_SIZE,
        max_size: int = DEFAULT_MAX_POOL_SIZE,
    ) -> IncidentDB:
        """Open a pool against ``dsn`` (default: the ``INCIDENT_DB_DSN`` env var).

        Raises ``ValueError`` when no DSN is available - check
        :func:`is_configured` before calling so an unconfigured deployment
        degrades instead of crashing - and propagates whatever
        ``asyncpg.create_pool`` itself raises for a malformed DSN or an
        unreachable host.
        """
        resolved_dsn = (dsn or _dsn_from_env()).strip()
        if not resolved_dsn:
            raise ValueError(f"{_DSN_ENV_VAR} is not set; incident DB is not configured")
        pool = await asyncpg.create_pool(dsn=resolved_dsn, min_size=min_size, max_size=max_size)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def __aenter__(self) -> IncidentDB:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            async with self._acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True, "ok"
        except (asyncpg.PostgresError, OSError) as exc:
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
        async with self._acquire() as conn:
            await conn.execute(
                """
                INSERT INTO videos (id, filepath, duration, source, uploaded_datetime)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    filepath = EXCLUDED.filepath,
                    duration = EXCLUDED.duration,
                    source = EXCLUDED.source
                """,
                video_id,
                filepath,
                duration,
                source,
                _utcnow(),
            )
        return video_id

    async def get_video(self, video_id: str, *, for_update: bool = False) -> dict[str, Any] | None:
        if for_update and self._connection is None:
            raise ValueError("for_update requires a transaction-bound writer")
        async with self._acquire() as conn:
            suffix = " FOR UPDATE" if for_update else ""
            row = await conn.fetchrow("SELECT * FROM videos WHERE id = $1" + suffix, video_id)
        return _row_to_dict(row)

    async def update_video(self, video_id: str, *, filepath: str | None) -> None:
        """Point an existing video row at its durable R2 object key."""
        async with self._acquire() as conn:
            await conn.execute("UPDATE videos SET filepath = $2 WHERE id = $1", video_id, filepath)

    async def list_videos(self) -> list[dict[str, Any]]:
        async with self._acquire() as conn:
            rows = await conn.fetch("SELECT * FROM videos ORDER BY id")
        return [dict(r) for r in rows]

    async def delete_video(self, video_id: str) -> None:
        async with self._acquire() as conn:
            await conn.execute("DELETE FROM videos WHERE id = $1", video_id)

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
        async with self._acquire() as conn:
            await conn.execute(
                """
                INSERT INTO model_runs (id, model_name, model_version, prompt_version, run_datetime, notes)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    model_name = EXCLUDED.model_name,
                    model_version = EXCLUDED.model_version,
                    prompt_version = EXCLUDED.prompt_version,
                    run_datetime = EXCLUDED.run_datetime,
                    notes = EXCLUDED.notes
                """,
                model_run_id,
                model_name,
                model_version,
                prompt_version,
                run_datetime or _utcnow(),
                notes,
            )
        return model_run_id

    async def get_model_run(self, model_run_id: str) -> dict[str, Any] | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM model_runs WHERE id = $1", model_run_id)
        return _row_to_dict(row)

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

        Mirrors ``db.py``'s delete-then-insert semantics, including resetting
        ``review_status`` back to ``unreviewed`` for this incident+run, inside
        one transaction.
        """
        payload = {k: (fields or {}).get(k) for k in self._INCIDENT_FIELDS}
        async with self._acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM incidents WHERE incident_id = $1 AND model_run_id = $2", incident_id, model_run_id
            )
            await conn.execute(
                """
                INSERT INTO incidents (
                    incident_id, model_run_id, type, start_timestamp, end_timestamp,
                    duration, description, severity_level, confidence_score
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                incident_id,
                model_run_id,
                payload["type"],
                payload["start_timestamp"],
                payload["end_timestamp"],
                payload["duration"],
                payload["description"],
                payload["severity_level"],
                payload["confidence_score"],
            )
            await conn.execute(
                "DELETE FROM review_status WHERE incident_id = $1 AND model_run_id = $2", incident_id, model_run_id
            )
            await conn.execute(
                "INSERT INTO review_status (incident_id, model_run_id, status) VALUES ($1, $2, 'unreviewed')",
                incident_id,
                model_run_id,
            )
        return incident_id, model_run_id

    async def get_incident(self, incident_id: str, model_run_id: str) -> dict[str, Any] | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM incidents WHERE incident_id = $1 AND model_run_id = $2", incident_id, model_run_id
            )
        return _row_to_dict(row)

    async def list_incidents(self, *, model_run_id: str | None = None) -> list[dict[str, Any]]:
        async with self._acquire() as conn:
            if model_run_id is not None:
                rows = await conn.fetch(
                    "SELECT * FROM incidents WHERE model_run_id = $1 ORDER BY incident_id", model_run_id
                )
            else:
                rows = await conn.fetch("SELECT * FROM incidents ORDER BY incident_id")
        return [dict(r) for r in rows]

    async def update_incident(self, incident_id: str, model_run_id: str, *, fields: dict[str, Any]) -> None:
        allowed = {k: v for k, v in fields.items() if k in self._INCIDENT_FIELDS}
        if not allowed:
            return
        set_clause = ", ".join(f"{col} = ${i + 3}" for i, col in enumerate(allowed))
        async with self._acquire() as conn:
            await conn.execute(
                f"UPDATE incidents SET {set_clause} WHERE incident_id = $1 AND model_run_id = $2",
                incident_id,
                model_run_id,
                *allowed.values(),
            )

    async def delete_incident(self, incident_id: str, model_run_id: str) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                "DELETE FROM incidents WHERE incident_id = $1 AND model_run_id = $2", incident_id, model_run_id
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
        async with self._acquire() as conn:
            await conn.execute(
                """
                INSERT INTO entities (incident_id, entity_id, model_run_id, type, description, image)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                incident_id,
                entity_id,
                model_run_id,
                type,
                description,
                image,
            )

    async def add_incident_instrument(
        self,
        incident_id: str,
        model_run_id: str,
        *,
        instrument_id: str,
        entity_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        threat_level: int | None = None,
        image: str | None = None,
    ) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                """
                INSERT INTO instruments (
                    incident_id, instrument_id, model_run_id, entity_id, name, description, threat_level, image
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                incident_id,
                instrument_id,
                model_run_id,
                entity_id,
                name,
                description,
                threat_level,
                image,
            )

    async def add_incident_asset(
        self,
        incident_id: str,
        model_run_id: str,
        *,
        asset_id: str,
        name: str | None = None,
        description: str | None = None,
        image: str | None = None,
    ) -> None:
        async with self._acquire() as conn:
            await conn.execute(
                """
                INSERT INTO assets (incident_id, asset_id, model_run_id, name, description, image)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                incident_id,
                asset_id,
                model_run_id,
                name,
                description,
                image,
            )

    async def list_incident_entities(self, incident_id: str, model_run_id: str | None = None) -> list[dict[str, Any]]:
        async with self._acquire() as conn:
            if model_run_id is not None:
                rows = await conn.fetch(
                    "SELECT * FROM entities WHERE incident_id = $1 AND model_run_id = $2 ORDER BY entity_id",
                    incident_id,
                    model_run_id,
                )
            else:
                rows = await conn.fetch("SELECT * FROM entities WHERE incident_id = $1 ORDER BY entity_id", incident_id)
        return [dict(r) for r in rows]

    async def list_incident_instruments(
        self, incident_id: str, model_run_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with self._acquire() as conn:
            if model_run_id is not None:
                rows = await conn.fetch(
                    "SELECT * FROM instruments WHERE incident_id = $1 AND model_run_id = $2 ORDER BY instrument_id",
                    incident_id,
                    model_run_id,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM instruments WHERE incident_id = $1 ORDER BY instrument_id", incident_id
                )
        return [dict(r) for r in rows]

    async def list_incident_assets(self, incident_id: str, model_run_id: str | None = None) -> list[dict[str, Any]]:
        async with self._acquire() as conn:
            if model_run_id is not None:
                rows = await conn.fetch(
                    "SELECT * FROM assets WHERE incident_id = $1 AND model_run_id = $2 ORDER BY asset_id",
                    incident_id,
                    model_run_id,
                )
            else:
                rows = await conn.fetch("SELECT * FROM assets WHERE incident_id = $1 ORDER BY asset_id", incident_id)
        return [dict(r) for r in rows]

    # -- review_status ------------------------------------------------------#
    async def get_review_status(self, incident_id: str, model_run_id: str) -> dict[str, Any] | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM review_status WHERE incident_id = $1 AND model_run_id = $2", incident_id, model_run_id
            )
        return _row_to_dict(row)

    async def set_review_status(
        self, incident_id: str, model_run_id: str, *, status: str, reviewed_by: str, notify_threshold: int
    ) -> dict[str, Any]:
        """Persist a review-status transition; raise a notification on verify above threshold.

        Mirrors ``db.py``'s ``set_review_status`` transaction semantics.
        """
        if status not in {"unreviewed", "under review", "verified"}:
            raise ValueError("Invalid review status")
        if not reviewed_by.strip():
            raise ValueError("Reviewer name is required")
        async with self._acquire() as conn, conn.transaction():
            incident_row = await conn.fetchrow(
                "SELECT severity_level FROM incidents WHERE incident_id = $1 AND model_run_id = $2",
                incident_id,
                model_run_id,
            )
            if incident_row is None:
                raise ValueError("Incident not found")
            severity = incident_row["severity_level"]
            current = await conn.fetchrow(
                "SELECT status FROM review_status WHERE incident_id = $1 AND model_run_id = $2",
                incident_id,
                model_run_id,
            )
            if current is not None and current["status"] == status:
                return {"notified": False, "severity": severity}
            now = _utcnow()
            cleaned_reviewer = reviewed_by.strip()
            await conn.execute(
                """
                UPDATE review_status SET
                    status = $3,
                    edited_by = $4,
                    edited_at = $5,
                    verified_by = CASE WHEN $3 = 'verified' THEN $4 ELSE NULL END,
                    verified_at = CASE WHEN $3 = 'verified' THEN $5 ELSE NULL END
                WHERE incident_id = $1 AND model_run_id = $2
                """,
                incident_id,
                model_run_id,
                status,
                cleaned_reviewer,
                now,
            )
            notified = status == "verified" and severity is not None and severity >= notify_threshold
            if notified:
                await conn.execute(
                    """
                    INSERT INTO notifications (incident_id, model_run_id, severity, created_at, acknowledged)
                    VALUES ($1, $2, $3, $4, FALSE)
                    """,
                    incident_id,
                    model_run_id,
                    severity,
                    now,
                )
        return {"notified": notified, "severity": severity}

    # -- notifications --------------------------------------------------#
    async def list_notifications(self, *, only_unacknowledged: bool = False) -> list[dict[str, Any]]:
        async with self._acquire() as conn:
            if only_unacknowledged:
                rows = await conn.fetch(
                    "SELECT * FROM notifications WHERE acknowledged = FALSE ORDER BY created_at DESC"
                )
            else:
                rows = await conn.fetch("SELECT * FROM notifications ORDER BY created_at DESC")
        return [dict(r) for r in rows]

    async def acknowledge_notification(self, notification_id: int) -> None:
        async with self._acquire() as conn:
            await conn.execute("UPDATE notifications SET acknowledged = TRUE WHERE id = $1", notification_id)

    # -- generated report documents (reports table) ----------------------#
    async def insert_generated_report(
        self,
        report_id: str,
        *,
        incident_id: str,
        model_run_id: str,
        query_id: str | None = None,
        filepath: str | None = None,
        generated_datetime: _dt.datetime | None = None,
    ) -> str:
        async with self._acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM reports WHERE id = $1", report_id)
            await conn.execute(
                """
                INSERT INTO reports (id, incident_id, query_id, model_run_id, filepath, generated_datetime)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                report_id,
                incident_id,
                query_id,
                model_run_id,
                filepath,
                generated_datetime or _utcnow(),
            )
        return report_id

    async def get_generated_report(self, report_id: str) -> dict[str, Any] | None:
        async with self._acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM reports WHERE id = $1", report_id)
        return _row_to_dict(row)


# --------------------------------------------------------------------------- #
# Module-level lazy singleton, mirroring db.py's own get_db()/reset_cache().
# --------------------------------------------------------------------------- #
_db: IncidentDB | None = None
_db_lock = asyncio.Lock()


async def get_db() -> IncidentDB | None:
    """Return the shared :class:`IncidentDB`, or ``None`` when unconfigured/unreachable.

    A missing ``INCIDENT_DB_DSN`` or a failed pool creation is swallowed so
    callers can treat the incident DB as an optional feature, matching
    ``db.py``'s own "database not configured" degrade-gracefully contract.
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
        except (asyncpg.PostgresError, OSError, ValueError) as exc:
            logger.warning("Incident DB unavailable: %s", exc)
            return None
    return _db


async def reset_cache() -> None:
    """Close and drop the cached pool (used by tests)."""
    global _db
    if _db is not None:
        await _db.close()
    _db = None
