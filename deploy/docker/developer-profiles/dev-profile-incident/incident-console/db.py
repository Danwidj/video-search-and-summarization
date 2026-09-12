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

Schema overview (multi-model-run + ground-truth evaluation):

- ``videos`` / ``queries`` / ``model_runs`` are the shared reference tables.
  **Identity rule: 1 video = 1 incident.** ``incidents.incident_id`` (and every
  other ``incident_id`` in this file) is the *same* string value as
  ``videos.id`` - there is no separate ``video_id`` column anywhere.
- ``incidents`` / ``entities`` / ``instruments`` / ``assets`` hold model output,
  keyed additionally by ``model_run_id`` so multiple models can be scored over
  the same video without overwriting each other.
- ``gt_incidents`` / ``gt_entities`` / ``gt_instruments`` / ``gt_assets`` hold
  the parallel human ground-truth set (no ``model_run_id``).
- ``entity_matches`` / ``instrument_matches`` / ``asset_matches`` hold accepted
  (above-threshold) similarity pairings between one model run's evidence and
  ground truth; see ``matching.py``. An absent row means "no accepted match".
- ``review_status`` is an additional table (not part of the binding 12) that
  carries the human review workflow (unreviewed / under review / verified)
  keyed the same way as ``incidents``, so the ``incidents`` table itself stays
  exactly as specified.
- ``notifications`` / ``severity_eval_log`` are existing tables, re-pointed at
  ``(incident_id, model_run_id)`` instead of the old integer report id.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.engine import Engine, make_url

import config


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


metadata = MetaData()

# --------------------------------------------------------------------------- #
# Shared reference tables
# --------------------------------------------------------------------------- #
videos = Table(
    "videos",
    metadata,
    Column("id", String(20), primary_key=True),
    Column("filepath", String(1024)),
    Column("uploaded_datetime", DateTime, default=_utcnow),
    Column("duration", Integer),
    Column("source", String(512)),
)

queries = Table(
    "queries",
    metadata,
    Column("id", String(20), primary_key=True),
    Column("query_text", Text, nullable=False),
    Column("submitted_datetime", DateTime, default=_utcnow),
)

model_runs = Table(
    "model_runs",
    metadata,
    Column("id", String(20), primary_key=True),
    Column("model_name", String(128), nullable=False),
    Column("model_version", String(128)),
    Column("prompt_version", String(64)),
    Column("run_datetime", DateTime, default=_utcnow),
    Column("notes", Text),
)

# --------------------------------------------------------------------------- #
# Model output
# --------------------------------------------------------------------------- #
incidents = Table(
    "incidents",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("type", String(32)),  # road accident / burglary / explosion / fighting / animal
    Column("start_timestamp", String(32)),  # HH:MM:SS
    Column("end_timestamp", String(32)),  # HH:MM:SS
    Column("duration", Integer),  # seconds
    Column("description", Text),
    Column("severity_level", Integer),  # 1-5
    Column("confidence_score", Float),
    ForeignKeyConstraint(["incident_id"], ["videos.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(["model_run_id"], ["model_runs.id"], ondelete="CASCADE"),
)

reports = Table(
    "reports",
    metadata,
    Column("id", String(20), primary_key=True),
    Column("incident_id", String(20), nullable=False),
    Column("query_id", String(20)),
    Column("model_run_id", String(20), nullable=False),
    Column("filepath", String(1024)),
    Column("generated_datetime", DateTime, default=_utcnow),
    ForeignKeyConstraint(["query_id"], ["queries.id"], ondelete="SET NULL"),
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
)

entities = Table(
    "entities",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("entity_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("type", String(16)),  # human / animal / unknown
    Column("description", Text),
    Column("image", String(1024)),  # R2 key; schema-only, always null for now
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
)

instruments = Table(
    "instruments",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("instrument_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("entity_id", String(20)),  # the wielding entity's entity_id, if any
    Column("name", String(256)),
    Column("description", Text),
    Column("threat_level", Integer),  # 1-5, NULL when not rated
    Column("image", String(1024)),
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
)

assets = Table(
    "assets",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("asset_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("name", String(256)),
    Column("description", Text),
    Column("image", String(1024)),
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
)

# --------------------------------------------------------------------------- #
# Human ground truth (parallel set, no model_run_id)
# --------------------------------------------------------------------------- #
gt_incidents = Table(
    "gt_incidents",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("type", String(32)),
    Column("start_timestamp", String(32)),
    Column("end_timestamp", String(32)),
    Column("duration", Integer),
    Column("description", Text),
    Column("severity_level", Integer),
    Column("labelled_by", String(256)),
    Column("labelled_datetime", DateTime),
    ForeignKeyConstraint(["incident_id"], ["videos.id"], ondelete="CASCADE"),
)

gt_entities = Table(
    "gt_entities",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("entity_id", String(20), primary_key=True),
    Column("type", String(16)),
    Column("description", Text),
    Column("image", String(1024)),
    ForeignKeyConstraint(["incident_id"], ["gt_incidents.incident_id"], ondelete="CASCADE"),
)

gt_instruments = Table(
    "gt_instruments",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("instrument_id", String(20), primary_key=True),
    Column("entity_id", String(20)),
    Column("name", String(256)),
    Column("description", Text),
    Column("threat_level", Integer),
    Column("image", String(1024)),
    ForeignKeyConstraint(["incident_id"], ["gt_incidents.incident_id"], ondelete="CASCADE"),
)

gt_assets = Table(
    "gt_assets",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("asset_id", String(20), primary_key=True),
    Column("name", String(256)),
    Column("description", Text),
    Column("image", String(1024)),
    ForeignKeyConstraint(["incident_id"], ["gt_incidents.incident_id"], ondelete="CASCADE"),
)

# --------------------------------------------------------------------------- #
# Similarity-match results (matching.py) - only accepted (above-threshold)
# pairings are ever written. An absent row means "no accepted match".
# --------------------------------------------------------------------------- #
entity_matches = Table(
    "entity_matches",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("entity_id", String(20), primary_key=True),
    Column("gt_entity_id", String(20), nullable=False),
    Column("similarity_score", Float, nullable=False),
    Column("matched_at", DateTime, default=_utcnow),
    ForeignKeyConstraint(
        ["incident_id", "entity_id", "model_run_id"],
        ["entities.incident_id", "entities.entity_id", "entities.model_run_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["incident_id", "gt_entity_id"], ["gt_entities.incident_id", "gt_entities.entity_id"], ondelete="CASCADE"
    ),
)

instrument_matches = Table(
    "instrument_matches",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("instrument_id", String(20), primary_key=True),
    Column("gt_instrument_id", String(20), nullable=False),
    Column("similarity_score", Float, nullable=False),
    Column("matched_at", DateTime, default=_utcnow),
    ForeignKeyConstraint(
        ["incident_id", "instrument_id", "model_run_id"],
        ["instruments.incident_id", "instruments.instrument_id", "instruments.model_run_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["incident_id", "gt_instrument_id"],
        ["gt_instruments.incident_id", "gt_instruments.instrument_id"],
        ondelete="CASCADE",
    ),
)

asset_matches = Table(
    "asset_matches",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("asset_id", String(20), primary_key=True),
    Column("gt_asset_id", String(20), nullable=False),
    Column("similarity_score", Float, nullable=False),
    Column("matched_at", DateTime, default=_utcnow),
    ForeignKeyConstraint(
        ["incident_id", "asset_id", "model_run_id"],
        ["assets.incident_id", "assets.asset_id", "assets.model_run_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["incident_id", "gt_asset_id"], ["gt_assets.incident_id", "gt_assets.asset_id"], ondelete="CASCADE"
    ),
)

# --------------------------------------------------------------------------- #
# Review workflow (additional table, not one of the literal 12 - see the
# module docstring) + existing notification / eval tables, re-pointed.
# --------------------------------------------------------------------------- #
review_status = Table(
    "review_status",
    metadata,
    Column("incident_id", String(20), primary_key=True),
    Column("model_run_id", String(20), primary_key=True),
    Column("status", String(32), nullable=False, default="unreviewed"),
    Column("verified_by", String(256)),
    Column("verified_at", DateTime),
    Column("edited_by", String(256)),
    Column("edited_at", DateTime),
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(20)),
    Column("model_run_id", String(20)),
    Column("severity", Integer),
    Column("created_at", DateTime, default=_utcnow),
    Column("acknowledged", Boolean, nullable=False, default=False),
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
)

severity_eval_log = Table(
    "severity_eval_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(20)),
    Column("model_run_id", String(20)),
    Column("ai_severity", Integer),
    Column("human_severity", Integer),
    Column("rater", String(256)),
    Column("rated_at", DateTime, default=_utcnow),
    ForeignKeyConstraint(
        ["incident_id", "model_run_id"], ["incidents.incident_id", "incidents.model_run_id"], ondelete="CASCADE"
    ),
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

    def healthcheck(self) -> tuple[bool, str]:
        try:
            with self.engine.connect() as conn:
                conn.execute(select(1))
            return True, "ok"
        except Exception as exc:  # noqa: BLE001 - surfaced verbatim in the UI
            return False, str(exc)

    # -- videos ---------------------------------------------------------- #
    def upsert_video(
        self,
        video_id: str,
        *,
        filepath: str | None = None,
        duration: int | None = None,
        source: str | None = None,
    ) -> str:
        """Insert or update the ``videos`` row for this id (the natural key)."""
        existing = self.get_video(video_id)
        with self.engine.begin() as conn:
            if existing:
                conn.execute(
                    update(videos)
                    .where(videos.c.id == video_id)
                    .values(filepath=filepath, duration=duration, source=source)
                )
            else:
                conn.execute(
                    videos.insert().values(
                        id=video_id,
                        filepath=filepath,
                        duration=duration,
                        source=source,
                        uploaded_datetime=_utcnow(),
                    )
                )
        return video_id

    def get_video(self, video_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(conn.execute(select(videos).where(videos.c.id == video_id)).first())

    def list_videos(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(select(videos).order_by(videos.c.id))]

    def list_videos_with_counts(self, *, filename_like: str | None = None, status: str | None = None) -> list[dict]:
        """Browse-only catalog rows: one per video, newest-review-status first.

        Read-only helper for the Catalog page. Each row carries the video's
        derived ``status`` - the review status of its most recent model run
        (``"unanalyzed"`` when no incident has been recorded against it yet) -
        and ``report_count``, the number of incident-report rows recorded for
        the video (``incident_id`` == ``videos.id``, so this counts
        ``incidents`` rows per video, one per model run).

        ``filename_like`` is a case-insensitive substring match on the
        filename; ``status`` other than ``None``/``"All"`` keeps only videos
        whose derived status matches.
        """
        with self.engine.connect() as conn:
            count_rows = conn.execute(
                select(incidents.c.incident_id, func.count().label("report_count")).group_by(incidents.c.incident_id)
            ).all()
        counts = {r._mapping["incident_id"]: int(r._mapping["report_count"]) for r in count_rows}
        latest_by_video = {r["incident_id"]: r for r in self.list_latest_incidents()}
        needle = (filename_like or "").strip().lower()
        result: list[dict] = []
        for video in self.list_videos():
            filename = (video.get("filepath") or "").rsplit("/", 1)[-1] or None
            latest = latest_by_video.get(video["id"])
            derived_status = (latest.get("status") or "unreviewed") if latest else "unanalyzed"
            if needle and needle not in (filename or "").lower():
                continue
            if status and status != "All" and derived_status != status:
                continue
            result.append(
                {
                    "id": video["id"],
                    "filename": filename,
                    "filepath": video.get("filepath"),
                    "status": derived_status,
                    "report_count": counts.get(video["id"], 0),
                    "duration": video.get("duration"),
                    "uploaded_datetime": video.get("uploaded_datetime"),
                }
            )
        return result

    def update_video(self, video_id: str, *, filepath: str | None) -> None:
        """Point this video's catalog row at a different R2 object."""
        with self.engine.begin() as conn:
            conn.execute(update(videos).where(videos.c.id == video_id).values(filepath=filepath))

    def delete_video(self, video_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(videos).where(videos.c.id == video_id))

    # -- queries ----------------------------------------------------------#
    def insert_query(self, query_id: str, *, query_text: str, submitted_datetime: _dt.datetime | None = None) -> str:
        """Insert or update-in-place - never delete-then-insert (see ``insert_model_run``)."""
        with self.engine.begin() as conn:
            values = {"query_text": query_text, "submitted_datetime": submitted_datetime or _utcnow()}
            if conn.execute(select(queries.c.id).where(queries.c.id == query_id)).first() is not None:
                conn.execute(update(queries).where(queries.c.id == query_id).values(**values))
            else:
                conn.execute(queries.insert().values(id=query_id, **values))
        return query_id

    def get_query(self, query_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(conn.execute(select(queries).where(queries.c.id == query_id)).first())

    def list_queries(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [
                _row_to_dict(r) for r in conn.execute(select(queries).order_by(queries.c.submitted_datetime.desc()))
            ]

    # -- model_runs ---------------------------------------------------- #
    def insert_model_run(
        self,
        model_run_id: str,
        *,
        model_name: str,
        model_version: str | None = None,
        prompt_version: str | None = None,
        run_datetime: _dt.datetime | None = None,
        notes: str | None = None,
    ) -> str:
        """Insert or update-in-place.

        Unlike ``insert_incident`` (which intentionally delete-then-inserts to
        reset a re-seeded incident's evidence/review state), this never deletes:
        ``incidents.model_run_id`` cascades on delete, so re-registering an
        existing run id would wipe every incident already recorded under it -
        exactly what happens when a seed batch shares one run id across many
        incidents.
        """
        with self.engine.begin() as conn:
            values = {
                "model_name": model_name,
                "model_version": model_version,
                "prompt_version": prompt_version,
                "run_datetime": run_datetime or _utcnow(),
                "notes": notes,
            }
            if conn.execute(select(model_runs.c.id).where(model_runs.c.id == model_run_id)).first() is not None:
                conn.execute(update(model_runs).where(model_runs.c.id == model_run_id).values(**values))
            else:
                conn.execute(model_runs.insert().values(id=model_run_id, **values))
        return model_run_id

    def get_model_run(self, model_run_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(conn.execute(select(model_runs).where(model_runs.c.id == model_run_id)).first())

    def list_model_runs(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [
                _row_to_dict(r) for r in conn.execute(select(model_runs).order_by(model_runs.c.run_datetime.desc()))
            ]

    # -- incidents (model output) --------------------------------------- #
    _INCIDENT_FIELDS = (
        "type",
        "start_timestamp",
        "end_timestamp",
        "duration",
        "description",
        "severity_level",
        "confidence_score",
    )

    def insert_incident(self, incident_id: str, model_run_id: str, *, fields: dict | None = None) -> tuple[str, str]:
        """Insert-or-replace one model run's incident row for ``incident_id``."""
        payload = {k: (fields or {}).get(k) for k in self._INCIDENT_FIELDS}
        with self.engine.begin() as conn:
            conn.execute(
                delete(incidents).where(
                    (incidents.c.incident_id == incident_id) & (incidents.c.model_run_id == model_run_id)
                )
            )
            conn.execute(incidents.insert().values(incident_id=incident_id, model_run_id=model_run_id, **payload))
            conn.execute(
                delete(review_status).where(
                    review_status.c.incident_id == incident_id, review_status.c.model_run_id == model_run_id
                )
            )
            conn.execute(
                review_status.insert().values(incident_id=incident_id, model_run_id=model_run_id, status="unreviewed")
            )
        return incident_id, model_run_id

    def get_incident(self, incident_id: str, model_run_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(
                conn.execute(
                    select(incidents).where(
                        (incidents.c.incident_id == incident_id) & (incidents.c.model_run_id == model_run_id)
                    )
                ).first()
            )

    def list_incidents(self, *, model_run_id: str | None = None) -> list[dict]:
        stmt = select(incidents).order_by(incidents.c.incident_id)
        if model_run_id is not None:
            stmt = stmt.where(incidents.c.model_run_id == model_run_id)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def update_incident(self, incident_id: str, model_run_id: str, *, fields: dict) -> None:
        allowed = {k: v for k, v in fields.items() if k in self._INCIDENT_FIELDS}
        if not allowed:
            return
        with self.engine.begin() as conn:
            conn.execute(
                update(incidents)
                .where((incidents.c.incident_id == incident_id) & (incidents.c.model_run_id == model_run_id))
                .values(**allowed)
            )

    def delete_incident(self, incident_id: str, model_run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(incidents).where(
                    (incidents.c.incident_id == incident_id) & (incidents.c.model_run_id == model_run_id)
                )
            )

    # -- incidents joined with video / model_run / review_status -------- #
    def _incident_view_rows(
        self,
        *,
        incident_id: str | None = None,
        model_run_id: str | None = None,
        type_: str | None = None,
        keyword: str | None = None,
    ) -> list[dict]:
        join = (
            incidents.join(model_runs, incidents.c.model_run_id == model_runs.c.id)
            .join(videos, incidents.c.incident_id == videos.c.id)
            .outerjoin(
                review_status,
                and_(
                    review_status.c.incident_id == incidents.c.incident_id,
                    review_status.c.model_run_id == incidents.c.model_run_id,
                ),
            )
        )
        stmt = select(
            incidents.c.incident_id,
            incidents.c.model_run_id,
            incidents.c.type,
            incidents.c.start_timestamp,
            incidents.c.end_timestamp,
            incidents.c.duration,
            incidents.c.description,
            incidents.c.severity_level,
            incidents.c.confidence_score,
            videos.c.filepath.label("video_filepath"),
            videos.c.duration.label("video_duration"),
            model_runs.c.model_name,
            model_runs.c.model_version,
            model_runs.c.run_datetime,
            review_status.c.status,
            review_status.c.verified_by,
            review_status.c.verified_at,
            review_status.c.edited_by,
            review_status.c.edited_at,
        ).select_from(join)
        if incident_id is not None:
            stmt = stmt.where(incidents.c.incident_id == incident_id)
        if model_run_id is not None:
            stmt = stmt.where(incidents.c.model_run_id == model_run_id)
        if type_ and type_ != "All":
            stmt = stmt.where(incidents.c.type == type_)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                incidents.c.description.ilike(like) | incidents.c.type.ilike(like) | videos.c.filepath.ilike(like)
            )
        stmt = stmt.order_by(model_runs.c.run_datetime.desc())
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_latest_incidents(self, *, type_: str | None = None, keyword: str | None = None) -> list[dict]:
        """One row per ``incident_id``: the most recent model run's incident."""
        seen: set[str] = set()
        result: list[dict] = []
        for row in self._incident_view_rows(type_=type_, keyword=keyword):
            if row["incident_id"] in seen:
                continue
            seen.add(row["incident_id"])
            result.append(row)
        return result

    def get_latest_incident(self, incident_id: str) -> dict:
        rows = self._incident_view_rows(incident_id=incident_id)
        return rows[0] if rows else {}

    # -- review_status ---------------------------------------------------#
    def get_review_status(self, incident_id: str, model_run_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(
                conn.execute(
                    select(review_status).where(
                        (review_status.c.incident_id == incident_id) & (review_status.c.model_run_id == model_run_id)
                    )
                ).first()
            )

    def touch_review_status(self, incident_id: str, model_run_id: str, *, edited_by: str | None) -> None:
        """Stamp ``edited_by``/``edited_at`` after a field edit, without changing status."""
        with self.engine.begin() as conn:
            conn.execute(
                update(review_status)
                .where((review_status.c.incident_id == incident_id) & (review_status.c.model_run_id == model_run_id))
                .values(edited_by=edited_by, edited_at=_utcnow())
            )

    def set_review_status(
        self, incident_id: str, model_run_id: str, *, status: str, reviewed_by: str, notify_threshold: int
    ) -> dict:
        """Persist a review-status transition; raise a notification on verify above threshold."""
        if status not in {"unreviewed", "under review", "verified"}:
            raise ValueError("Invalid review status")
        if not reviewed_by.strip():
            raise ValueError("Reviewer name is required")
        with self.engine.begin() as conn:
            incident_row = conn.execute(
                select(incidents.c.severity_level).where(
                    (incidents.c.incident_id == incident_id) & (incidents.c.model_run_id == model_run_id)
                )
            ).first()
            if incident_row is None:
                raise ValueError("Incident not found")
            severity = incident_row._mapping["severity_level"]
            current = conn.execute(
                select(review_status.c.status).where(
                    (review_status.c.incident_id == incident_id) & (review_status.c.model_run_id == model_run_id)
                )
            ).first()
            if current is not None and current._mapping["status"] == status:
                return {"notified": False, "severity": severity}
            now = _utcnow()
            conn.execute(
                update(review_status)
                .where((review_status.c.incident_id == incident_id) & (review_status.c.model_run_id == model_run_id))
                .values(
                    status=status,
                    edited_by=reviewed_by.strip(),
                    edited_at=now,
                    verified_by=reviewed_by.strip() if status == "verified" else None,
                    verified_at=now if status == "verified" else None,
                )
            )
            notified = status == "verified" and severity is not None and severity >= notify_threshold
            if notified:
                conn.execute(
                    notifications.insert().values(
                        incident_id=incident_id,
                        model_run_id=model_run_id,
                        severity=severity,
                        created_at=now,
                        acknowledged=False,
                    )
                )
            return {"notified": notified, "severity": severity}

    # -- entities / instruments / assets (model output) ------------------ #
    def add_incident_entity(
        self,
        incident_id: str,
        model_run_id: str,
        *,
        entity_id: str,
        type: str | None = None,
        description: str | None = None,
        image: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                entities.insert().values(
                    incident_id=incident_id,
                    entity_id=entity_id,
                    model_run_id=model_run_id,
                    type=type,
                    description=description,
                    image=image,
                )
            )

    def add_incident_instrument(
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
        with self.engine.begin() as conn:
            conn.execute(
                instruments.insert().values(
                    incident_id=incident_id,
                    instrument_id=instrument_id,
                    model_run_id=model_run_id,
                    entity_id=entity_id,
                    name=name,
                    description=description,
                    threat_level=threat_level,
                    image=image,
                )
            )

    def add_incident_asset(
        self,
        incident_id: str,
        model_run_id: str,
        *,
        asset_id: str,
        name: str | None = None,
        description: str | None = None,
        image: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                assets.insert().values(
                    incident_id=incident_id,
                    asset_id=asset_id,
                    model_run_id=model_run_id,
                    name=name,
                    description=description,
                    image=image,
                )
            )

    def list_incident_entities(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        stmt = select(entities).where(entities.c.incident_id == incident_id).order_by(entities.c.entity_id)
        if model_run_id is not None:
            stmt = stmt.where(entities.c.model_run_id == model_run_id)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_incident_instruments(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        stmt = select(instruments).where(instruments.c.incident_id == incident_id).order_by(instruments.c.instrument_id)
        if model_run_id is not None:
            stmt = stmt.where(instruments.c.model_run_id == model_run_id)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_incident_assets(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        stmt = select(assets).where(assets.c.incident_id == incident_id).order_by(assets.c.asset_id)
        if model_run_id is not None:
            stmt = stmt.where(assets.c.model_run_id == model_run_id)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def clear_incident_evidence(self, incident_id: str, model_run_id: str) -> None:
        """Drop all entity/instrument/asset rows for one incident+run (seed re-import)."""
        with self.engine.begin() as conn:
            for table in (entities, instruments, assets):
                conn.execute(
                    delete(table).where((table.c.incident_id == incident_id) & (table.c.model_run_id == model_run_id))
                )

    # -- ground truth ------------------------------------------------ #
    _GT_INCIDENT_FIELDS = (
        "type",
        "start_timestamp",
        "end_timestamp",
        "duration",
        "description",
        "severity_level",
        "labelled_by",
        "labelled_datetime",
    )

    def insert_gt_incident(self, incident_id: str, *, fields: dict | None = None) -> str:
        payload = {k: (fields or {}).get(k) for k in self._GT_INCIDENT_FIELDS}
        with self.engine.begin() as conn:
            conn.execute(delete(gt_incidents).where(gt_incidents.c.incident_id == incident_id))
            conn.execute(gt_incidents.insert().values(incident_id=incident_id, **payload))
        return incident_id

    def get_gt_incident(self, incident_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(
                conn.execute(select(gt_incidents).where(gt_incidents.c.incident_id == incident_id)).first()
            )

    def list_gt_incidents(self) -> list[dict]:
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(select(gt_incidents).order_by(gt_incidents.c.incident_id))]

    def add_gt_entity(
        self,
        incident_id: str,
        *,
        entity_id: str,
        type: str | None = None,
        description: str | None = None,
        image: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                gt_entities.insert().values(
                    incident_id=incident_id, entity_id=entity_id, type=type, description=description, image=image
                )
            )

    def add_gt_instrument(
        self,
        incident_id: str,
        *,
        instrument_id: str,
        entity_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
        threat_level: int | None = None,
        image: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                gt_instruments.insert().values(
                    incident_id=incident_id,
                    instrument_id=instrument_id,
                    entity_id=entity_id,
                    name=name,
                    description=description,
                    threat_level=threat_level,
                    image=image,
                )
            )

    def add_gt_asset(
        self,
        incident_id: str,
        *,
        asset_id: str,
        name: str | None = None,
        description: str | None = None,
        image: str | None = None,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                gt_assets.insert().values(
                    incident_id=incident_id, asset_id=asset_id, name=name, description=description, image=image
                )
            )

    def list_gt_entities(self, incident_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            stmt = select(gt_entities).where(gt_entities.c.incident_id == incident_id).order_by(gt_entities.c.entity_id)
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_gt_instruments(self, incident_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            stmt = (
                select(gt_instruments)
                .where(gt_instruments.c.incident_id == incident_id)
                .order_by(gt_instruments.c.instrument_id)
            )
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_gt_assets(self, incident_id: str) -> list[dict]:
        with self.engine.connect() as conn:
            stmt = select(gt_assets).where(gt_assets.c.incident_id == incident_id).order_by(gt_assets.c.asset_id)
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    # -- similarity matches (matching.py) ------------------------------- #
    def record_entity_match(
        self, *, incident_id: str, model_run_id: str, entity_id: str, gt_entity_id: str, similarity_score: float
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(entity_matches).where(
                    (entity_matches.c.incident_id == incident_id)
                    & (entity_matches.c.model_run_id == model_run_id)
                    & (entity_matches.c.entity_id == entity_id)
                )
            )
            conn.execute(
                entity_matches.insert().values(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    entity_id=entity_id,
                    gt_entity_id=gt_entity_id,
                    similarity_score=similarity_score,
                    matched_at=_utcnow(),
                )
            )

    def record_instrument_match(
        self, *, incident_id: str, model_run_id: str, instrument_id: str, gt_instrument_id: str, similarity_score: float
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(instrument_matches).where(
                    (instrument_matches.c.incident_id == incident_id)
                    & (instrument_matches.c.model_run_id == model_run_id)
                    & (instrument_matches.c.instrument_id == instrument_id)
                )
            )
            conn.execute(
                instrument_matches.insert().values(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    instrument_id=instrument_id,
                    gt_instrument_id=gt_instrument_id,
                    similarity_score=similarity_score,
                    matched_at=_utcnow(),
                )
            )

    def record_asset_match(
        self, *, incident_id: str, model_run_id: str, asset_id: str, gt_asset_id: str, similarity_score: float
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                delete(asset_matches).where(
                    (asset_matches.c.incident_id == incident_id)
                    & (asset_matches.c.model_run_id == model_run_id)
                    & (asset_matches.c.asset_id == asset_id)
                )
            )
            conn.execute(
                asset_matches.insert().values(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    asset_id=asset_id,
                    gt_asset_id=gt_asset_id,
                    similarity_score=similarity_score,
                    matched_at=_utcnow(),
                )
            )

    def list_entity_matches(self, incident_id: str, model_run_id: str) -> list[dict]:
        stmt = select(entity_matches).where(
            (entity_matches.c.incident_id == incident_id) & (entity_matches.c.model_run_id == model_run_id)
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_instrument_matches(self, incident_id: str, model_run_id: str) -> list[dict]:
        stmt = select(instrument_matches).where(
            (instrument_matches.c.incident_id == incident_id) & (instrument_matches.c.model_run_id == model_run_id)
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    def list_asset_matches(self, incident_id: str, model_run_id: str) -> list[dict]:
        stmt = select(asset_matches).where(
            (asset_matches.c.incident_id == incident_id) & (asset_matches.c.model_run_id == model_run_id)
        )
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

    # -- generated report documents (reports table) ----------------- #
    def insert_generated_report(
        self,
        report_id: str,
        *,
        incident_id: str,
        model_run_id: str,
        query_id: str | None = None,
        filepath: str | None = None,
        generated_datetime: _dt.datetime | None = None,
    ) -> str:
        with self.engine.begin() as conn:
            conn.execute(delete(reports).where(reports.c.id == report_id))
            conn.execute(
                reports.insert().values(
                    id=report_id,
                    incident_id=incident_id,
                    model_run_id=model_run_id,
                    query_id=query_id,
                    filepath=filepath,
                    generated_datetime=generated_datetime or _utcnow(),
                )
            )
        return report_id

    def get_generated_report(self, report_id: str) -> dict:
        with self.engine.connect() as conn:
            return _row_to_dict(conn.execute(select(reports).where(reports.c.id == report_id)).first())

    def list_generated_reports(self, *, incident_id: str | None = None) -> list[dict]:
        stmt = select(reports).order_by(reports.c.generated_datetime.desc())
        if incident_id is not None:
            stmt = stmt.where(reports.c.incident_id == incident_id)
        with self.engine.connect() as conn:
            return [_row_to_dict(r) for r in conn.execute(stmt)]

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
    def insert_severity_eval(
        self, *, incident_id: str, model_run_id: str, ai_severity: int, human_severity: int, rater: str
    ) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                severity_eval_log.insert().values(
                    incident_id=incident_id,
                    model_run_id=model_run_id,
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
