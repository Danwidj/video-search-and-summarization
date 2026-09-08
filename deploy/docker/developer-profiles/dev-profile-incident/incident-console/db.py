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

"""Direct-Postgres data layer for the incident console.

Sync SQLAlchemy Core (matches Streamlit's per-rerun execution model). Every
catalog / edit / verify / dashboard / eval read and write goes through here.
Schema is created with ``CREATE TABLE IF NOT EXISTS`` semantics
(``MetaData.create_all(checkfirst=True)``) once on startup - no Alembic.

The connection string comes from ``INCIDENT_DB_DSN``. When it is unset,
``get_db()`` returns ``None`` and the app renders a "database not configured"
state so it stays reviewable without live infra. The pool is kept small because
Cloudflare Hyperdrive already pools.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine, make_url

import config


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


# JSONB on Postgres, plain JSON everywhere else (SQLite in tests).
_JSON = JSON().with_variant(JSONB(), "postgresql")

metadata = MetaData()

videos = Table(
    "videos",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("filename", String(512), nullable=False),
    Column("r2_key", String(1024)),
    Column("uploaded_at", DateTime, default=_utcnow),
    Column("status", String(32), nullable=False, default="unanalyzed"),
    Column("location", String(512)),
    Column("camera_source", String(512)),
    Column("metadata_edited_by", String(256)),
    Column("metadata_edited_at", DateTime),
    Column("sensor_id", String(256)),
    Column("error_message", Text),
    # Additive: clip length in seconds when known (probed from the source).
    Column("duration_sec", Integer),
)

incident_reports = Table(
    "incident_reports",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("video_id", Integer, ForeignKey("videos.id", ondelete="CASCADE")),
    Column("incident_type", String(64)),
    Column("severity", Integer),
    Column("confidence", Float),
    Column("incident_start", String(32)),
    Column("incident_end", String(32)),
    Column("incident_start_confirmed", Boolean, default=False),
    Column("description", Text),
    Column("persons", _JSON, default=list),
    Column("location", String(512)),
    Column("status", String(32), nullable=False, default="unreviewed"),
    Column("verified_by", String(256)),
    Column("verified_at", DateTime),
    Column("edited_by", String(256)),
    Column("edited_at", DateTime),
    Column("created_at", DateTime, default=_utcnow),
    # Additive columns (see dev-profile-incident 8-mock seed task). Existing
    # profiles keep working: is_synthetic defaults true, the other two are
    # nullable and simply stay NULL for rows that never set them.
    Column("is_synthetic", Boolean, nullable=False, default=True),
    Column("duration_sec", Integer),
    Column("model_version", String(128)),
)

# Structured evidence linked to an incident report, modeled on
# fixtures/data/{entities,instruments,assets}.csv. Additive: no existing profile
# reads or writes these; the 8-mock Supabase seed is their only current source.
incident_entities = Table(
    "incident_entities",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False),
    Column("local_id", String(16)),  # incident-scoped handle, e.g. "E1"
    Column("type", String(16)),  # human / animal / unknown
    Column("description", Text),
    # Object-storage key (R2) for a cropped screenshot. Bytes never live in
    # Postgres; the file is uploaded separately and only its key is stored.
    Column("image_key", String(1024)),
    Column("is_synthetic", Boolean, nullable=False, default=True),
)

incident_instruments = Table(
    "incident_instruments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False),
    Column("local_id", String(16)),  # e.g. "I1"
    Column("entity_local_id", String(16)),  # the wielding entity's local_id, if any
    Column("name", String(256)),
    Column("description", Text),
    Column("threat_level", Integer),  # 1-5 rubric, NULL when not rated
    Column("image_key", String(1024)),  # R2 screenshot key; see incident_entities
    Column("is_synthetic", Boolean, nullable=False, default=True),
)

incident_assets = Table(
    "incident_assets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, ForeignKey("incident_reports.id", ondelete="CASCADE"), nullable=False),
    Column("local_id", String(16)),  # e.g. "A1"
    Column("name", String(256)),
    Column("description", Text),
    Column("image_key", String(1024)),  # R2 screenshot key; see incident_entities
    Column("is_synthetic", Boolean, nullable=False, default=True),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, ForeignKey("incident_reports.id", ondelete="CASCADE")),
    Column("severity", Integer),
    Column("created_at", DateTime, default=_utcnow),
    Column("acknowledged", Boolean, nullable=False, default=False),
)

severity_eval_log = Table(
    "severity_eval_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_id", Integer, ForeignKey("incident_reports.id", ondelete="CASCADE")),
    Column("ai_severity", Integer),
    Column("human_severity", Integer),
    Column("rater", String(256)),
    Column("rated_at", DateTime, default=_utcnow),
)


def _row_to_dict(row: Any) -> dict:
    return dict(row._mapping) if row is not None else {}


class IncidentDB:
    """Thin CRUD wrapper around one SQLAlchemy engine."""

    def __init__(self, engine: Engine):
        self.engine = engine

    # -- lifecycle ------------------------------------------------------- #
    @classmethod
    def from_dsn(cls, dsn: str, **engine_kwargs: Any) -> IncidentDB:
        url = make_url(dsn)
        kwargs: dict[str, Any] = {"pool_pre_ping": True, "future": True}
        if url.get_backend_name() != "sqlite":
            # Hyperdrive already pools; keep the app-side pool small.
            kwargs.update(pool_size=2, max_overflow=3)
        kwargs.update(engine_kwargs)
        return cls(create_engine(url, **kwargs))

    def init_schema(self) -> None:
        metadata.create_all(self.engine, checkfirst=True)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """Additive, idempotent column backfill for tables that predate this file.

        ``MetaData.create_all`` only creates whole missing tables; it never adds a
        column to a table that already exists. The columns below were appended to
        ``videos`` / ``incident_reports`` after other profiles had already created
        those tables, so bring an older schema forward here. Every column is
        nullable or carries a default, so the ``ALTER`` is safe to repeat.
        """
        from sqlalchemy import inspect as _inspect
        from sqlalchemy import text as _text

        pending: dict[str, list[str]] = {
            "videos": ["duration_sec"],
            "incident_reports": ["is_synthetic", "duration_sec", "model_version"],
            "incident_entities": ["image_key"],
            "incident_instruments": ["image_key"],
            "incident_assets": ["image_key"],
        }
        ddl = {
            ("videos", "duration_sec"): "INTEGER",
            ("incident_reports", "duration_sec"): "INTEGER",
            ("incident_reports", "model_version"): "VARCHAR(128)",
            ("incident_reports", "is_synthetic"): "BOOLEAN NOT NULL DEFAULT TRUE",
            ("incident_entities", "image_key"): "VARCHAR(1024)",
            ("incident_instruments", "image_key"): "VARCHAR(1024)",
            ("incident_assets", "image_key"): "VARCHAR(1024)",
        }
        inspector = _inspect(self.engine)
        existing_tables = set(inspector.get_table_names())
        statements: list[str] = []
        for table_name, columns in pending.items():
            if table_name not in existing_tables:
                continue  # create_all just made it with every column
            have = {c["name"] for c in inspector.get_columns(table_name)}
            statements.extend(
                f"ALTER TABLE {table_name} ADD COLUMN {column} {ddl[(table_name, column)]}"
                for column in columns
                if column not in have
            )
        if not statements:
            return
        with self.engine.begin() as conn:
            for statement in statements:
                conn.execute(_text(statement))

    def healthcheck(self) -> tuple[bool, str]:
        try:
            with self.engine.connect() as conn:
                conn.execute(select(1))
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim in the UI
            return False, str(exc)

    # -- videos -------------------------------------------------------- #
    def insert_video(
        self,
        *,
        filename: str,
        r2_key: str | None = None,
        status: str = "unanalyzed",
        location: str | None = None,
        camera_source: str | None = None,
        sensor_id: str | None = None,
        duration_sec: int | None = None,
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                videos.insert().values(
                    filename=filename,
                    r2_key=r2_key,
                    status=status,
                    location=location,
                    camera_source=camera_source,
                    sensor_id=sensor_id,
                    duration_sec=duration_sec,
                    uploaded_at=_utcnow(),
                )
            )
            return int(result.inserted_primary_key[0])

    def get_video_by_r2_key(self, r2_key: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(conn.execute(select(videos).where(videos.c.r2_key == r2_key)).first())

    def upsert_video_by_r2_key(
        self,
        *,
        r2_key: str,
        filename: str,
        status: str = "analyzed",
        duration_sec: int | None = None,
    ) -> int:
        """Insert or update the catalog row for one R2 object, keyed on ``r2_key``.

        The stable natural key lets the one-time Supabase seed importer re-run
        without creating duplicate ``videos`` rows.
        """
        existing = self.get_video_by_r2_key(r2_key)
        if existing:
            with self.engine.begin() as conn:
                conn.execute(
                    update(videos)
                    .where(videos.c.id == existing["id"])
                    .values(filename=filename, status=status, duration_sec=duration_sec)
                )
            return int(existing["id"])
        return self.insert_video(filename=filename, r2_key=r2_key, status=status, duration_sec=duration_sec)

    def list_videos(
        self,
        *,
        filename_like: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        stmt = select(videos).order_by(videos.c.id.desc())
        if filename_like:
            stmt = stmt.where(videos.c.filename.ilike(f"%{filename_like}%"))
        if status and status != "All":
            stmt = stmt.where(videos.c.status == status)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def get_video(self, video_id: int) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(conn.execute(select(videos).where(videos.c.id == video_id)).first())

    def update_video_metadata(
        self,
        video_id: int,
        *,
        location: str | None,
        camera_source: str | None,
        edited_by: str,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(videos)
                .where(videos.c.id == video_id)
                .values(
                    location=location,
                    camera_source=camera_source,
                    metadata_edited_by=edited_by,
                    metadata_edited_at=_utcnow(),
                )
            )

    def set_video_status(self, video_id: int, status: str, error_message: str | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(videos).where(videos.c.id == video_id).values(status=status, error_message=error_message)
            )

    def delete_video(self, video_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(videos).where(videos.c.id == video_id))

    # -- incident_reports -------------------------------------------- #
    def insert_report(self, *, video_id: int | None, report: dict) -> int:
        payload = {
            k: report.get(k)
            for k in (
                "incident_type",
                "severity",
                "confidence",
                "incident_start",
                "incident_end",
                "incident_start_confirmed",
                "description",
                "persons",
                "location",
                "duration_sec",
                "model_version",
            )
        }
        payload["video_id"] = video_id
        payload["status"] = report.get("status", "unreviewed")
        # Additive column: default true so unmarked callers still validate; the
        # 8-mock seed sets it explicitly.
        payload["is_synthetic"] = report.get("is_synthetic", True)
        payload["created_at"] = _utcnow()
        with self.engine.begin() as conn:
            result = conn.execute(incident_reports.insert().values(**payload))
            return int(result.inserted_primary_key[0])

    def list_reports(
        self,
        *,
        incident_type: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[dict]:
        stmt = select(incident_reports).order_by(incident_reports.c.id.desc())
        if incident_type and incident_type != "All":
            stmt = stmt.where(incident_reports.c.incident_type == incident_type)
        if status and status != "All":
            stmt = stmt.where(incident_reports.c.status == status)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                incident_reports.c.description.ilike(like)
                | incident_reports.c.location.ilike(like)
                | incident_reports.c.incident_type.ilike(like)
            )
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def get_report(self, report_id: int) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(
                conn.execute(select(incident_reports).where(incident_reports.c.id == report_id)).first()
            )

    def get_report_by_video_id(self, video_id: int) -> dict:
        """First report attached to a video. The 8-mock seed keeps one per clip."""
        with self.engine.connect() as conn:
            return _row_to_dict(
                conn.execute(
                    select(incident_reports)
                    .where(incident_reports.c.video_id == video_id)
                    .order_by(incident_reports.c.id.asc())
                ).first()
            )

    def update_report(self, report_id: int, *, fields: dict, edited_by: str) -> None:
        allowed = {
            k: v
            for k, v in fields.items()
            if k
            in {
                "incident_type",
                "severity",
                "confidence",
                "incident_start",
                "incident_end",
                "incident_start_confirmed",
                "description",
                "persons",
                "location",
                "duration_sec",
                "model_version",
                "is_synthetic",
            }
        }
        allowed["edited_by"] = edited_by
        allowed["edited_at"] = _utcnow()
        with self.engine.begin() as conn:
            conn.execute(update(incident_reports).where(incident_reports.c.id == report_id).values(**allowed))

    def verify_report(self, report_id: int, *, verified_by: str, notify_threshold: int) -> dict:
        """Mark a report verified; raise a notification when severity clears the threshold.

        Returns ``{"notified": bool, "severity": int}``.
        """
        with self.engine.begin() as conn:
            row = conn.execute(select(incident_reports).where(incident_reports.c.id == report_id)).first()
            if row is None:
                return {"notified": False, "severity": None}
            severity = row._mapping["severity"]
            conn.execute(
                update(incident_reports)
                .where(incident_reports.c.id == report_id)
                .values(
                    status="verified",
                    verified_by=verified_by,
                    verified_at=_utcnow(),
                )
            )
            notified = False
            try:
                if severity is not None and int(severity) >= int(notify_threshold):
                    conn.execute(
                        notifications.insert().values(
                            report_id=report_id,
                            severity=int(severity),
                            created_at=_utcnow(),
                            acknowledged=False,
                        )
                    )
                    notified = True
            except (TypeError, ValueError):
                pass
        return {"notified": notified, "severity": severity}

    def set_report_review_status(self, report_id: int, *, status: str, reviewed_by: str, notify_threshold: int) -> dict:
        """Persist review transitions with existing attribution columns, atomically.

        No new schema fields. Repeating a status does not duplicate alerts.
        Existing verify_report remains available to its other callers.
        """
        if status not in {"unreviewed", "under review", "verified"}:
            raise ValueError("Invalid review status")
        if not reviewed_by.strip():
            raise ValueError("Reviewer name is required")
        with self.engine.begin() as conn:
            row = conn.execute(
                select(incident_reports).where(incident_reports.c.id == report_id).with_for_update()
            ).first()
            if row is None:
                raise ValueError("Report not found")
            current = row._mapping
            if current["status"] == status:
                return {"notified": False, "severity": current["severity"]}
            now = _utcnow()
            conn.execute(
                update(incident_reports)
                .where(incident_reports.c.id == report_id)
                .values(
                    status=status,
                    edited_by=reviewed_by.strip(),
                    edited_at=now,
                    verified_by=reviewed_by.strip() if status == "verified" else None,
                    verified_at=now if status == "verified" else None,
                )
            )
            severity = current["severity"]
            notified = status == "verified" and severity is not None and severity >= notify_threshold
            if notified:
                conn.execute(
                    notifications.insert().values(
                        report_id=report_id,
                        severity=severity,
                        created_at=now,
                        acknowledged=False,
                    )
                )
            return {"notified": notified, "severity": severity}

    def delete_report(self, report_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(incident_reports).where(incident_reports.c.id == report_id))

    def link_report_video(self, report_id: int, video_id: int | None, *, edited_by: str | None = None) -> None:
        """Point a report at a different ``videos`` row (or clear the link)."""
        values: dict[str, Any] = {"video_id": video_id}
        if edited_by:
            values["edited_by"] = edited_by
            values["edited_at"] = _utcnow()
        with self.engine.begin() as conn:
            conn.execute(update(incident_reports).where(incident_reports.c.id == report_id).values(**values))

    # -- incident evidence (entities / instruments / assets) ------- #
    @staticmethod
    def _evidence_table(kind: str) -> Table:
        return {
            "entities": incident_entities,
            "instruments": incident_instruments,
            "assets": incident_assets,
        }[kind]

    def add_incident_entity(
        self,
        report_id: int,
        *,
        local_id: str | None = None,
        type: str | None = None,
        description: str | None = None,
        image_key: str | None = None,
        is_synthetic: bool = True,
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                incident_entities.insert().values(
                    report_id=report_id,
                    local_id=local_id,
                    type=type,
                    description=description,
                    image_key=image_key,
                    is_synthetic=is_synthetic,
                )
            )
            return int(result.inserted_primary_key[0])

    def add_incident_instrument(
        self,
        report_id: int,
        *,
        local_id: str | None = None,
        entity_local_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        threat_level: int | None = None,
        image_key: str | None = None,
        is_synthetic: bool = True,
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                incident_instruments.insert().values(
                    report_id=report_id,
                    local_id=local_id,
                    entity_local_id=entity_local_id,
                    name=name,
                    description=description,
                    threat_level=threat_level,
                    image_key=image_key,
                    is_synthetic=is_synthetic,
                )
            )
            return int(result.inserted_primary_key[0])

    def add_incident_asset(
        self,
        report_id: int,
        *,
        local_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        image_key: str | None = None,
        is_synthetic: bool = True,
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                incident_assets.insert().values(
                    report_id=report_id,
                    local_id=local_id,
                    name=name,
                    description=description,
                    image_key=image_key,
                    is_synthetic=is_synthetic,
                )
            )
            return int(result.inserted_primary_key[0])

    def list_incident_entities(self, report_id: int | None = None) -> list[dict]:
        return self._list_evidence("entities", report_id)

    def list_incident_instruments(self, report_id: int | None = None) -> list[dict]:
        return self._list_evidence("instruments", report_id)

    def list_incident_assets(self, report_id: int | None = None) -> list[dict]:
        return self._list_evidence("assets", report_id)

    def _list_evidence(self, kind: str, report_id: int | None) -> list[dict]:
        table = self._evidence_table(kind)
        stmt = select(table).order_by(table.c.id.asc())
        if report_id is not None:
            stmt = stmt.where(table.c.report_id == report_id)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def clear_incident_evidence(self, report_id: int) -> None:
        """Drop all entity/instrument/asset rows for a report (seed re-import)."""
        with self.engine.begin() as conn:
            for table in (incident_entities, incident_instruments, incident_assets):
                conn.execute(delete(table).where(table.c.report_id == report_id))

    # -- notifications --------------------------------------------- #
    def list_notifications(self, *, only_unacknowledged: bool = False) -> list[dict]:
        stmt = select(notifications).order_by(notifications.c.created_at.desc())
        if only_unacknowledged:
            stmt = stmt.where(notifications.c.acknowledged.is_(False))
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def acknowledge_notification(self, notification_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(notifications).where(notifications.c.id == notification_id).values(acknowledged=True))

    # -- severity_eval_log --------------------------------------- #
    def insert_severity_eval(self, *, report_id: int, ai_severity: int, human_severity: int, rater: str) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                severity_eval_log.insert().values(
                    report_id=report_id,
                    ai_severity=ai_severity,
                    human_severity=human_severity,
                    rater=rater,
                    rated_at=_utcnow(),
                )
            )
            return int(result.inserted_primary_key[0])

    def list_severity_evals(self) -> list[dict]:
        stmt = select(severity_eval_log).order_by(severity_eval_log.c.id.desc())
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def severity_eval_counts(self) -> dict:
        with self.engine.connect() as conn:
            total = conn.execute(select(func.count()).select_from(severity_eval_log)).scalar_one()
        return {"total": int(total or 0)}


# --------------------------------------------------------------------------- #
# Module-level lazy singleton keyed on the configured DSN
# --------------------------------------------------------------------------- #
_db: IncidentDB | None = None
_db_dsn: str | None = None


def is_configured() -> bool:
    return bool(config.incident_db_dsn())


def get_db() -> IncidentDB | None:
    """Return the shared :class:`IncidentDB`, or ``None`` when no DSN is set.

    The schema is created on first successful construction. A construction
    failure (bad DSN, unreachable host) is swallowed and ``None`` returned so
    the app degrades to a "database not configured / unreachable" state.
    """
    global _db, _db_dsn
    dsn = config.incident_db_dsn()
    if not dsn:
        return None
    if _db is not None and _db_dsn == dsn:
        return _db
    try:
        db = IncidentDB.from_dsn(dsn)
        db.init_schema()
    except Exception:  # noqa: BLE001 - callers show a friendly state
        return None
    _db, _db_dsn = db, dsn
    return _db


def reset_cache() -> None:
    """Drop the cached engine (used by tests)."""
    global _db, _db_dsn
    if _db is not None:
        _db.engine.dispose()
    _db, _db_dsn = None, None
