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

"""Database-free store for scoring: the ``IncidentDB`` methods the evaluator uses, held in memory.

``eval_gt.run_evaluation`` and ``matching.match_incident`` read ground truth and
predictions through a store handle and record accepted matches back into it. The
finals Supabase project no longer has the tables ``db.py`` maps (``gt_*``,
``incidents``, ``entities``, ``instruments``, ``assets``, ``*_matches``), so the
default for ``eval_run.py`` is this store: nothing is opened, connected to or
created. ``eval_run.py --db`` keeps the old database path for a database that
still has those tables.

The store is a drop-in for the scorer, not a new scorer: it keeps the same
semantics as ``IncidentDB`` where scoring can observe them -

* rows carry every column of the ``db.py`` table, missing values ``None``;
* values are coerced the way a SQL column of that type returns them (a float
  ``12.0`` written to a ``VARCHAR`` comes back as ``'12.0'``, a ``3.0`` written to
  an ``INTEGER`` as ``3``), so stored expected/predicted values match the
  database path exactly;
* list methods order by the item id, as ``ORDER BY`` does (codepoint order);
* re-inserting an incident (model or ground truth) replaces it and removes its
  evidence rows and matches, as the database's ``ON DELETE CASCADE`` does.

``tests/test_offline_store.py`` proves score equivalence against the SQLite
``IncidentDB`` the existing tests use.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import db as db_module
from sqlalchemy import Float, Integer, String, Text

_TABLES = (
    "videos",
    "model_runs",
    "incidents",
    "entities",
    "instruments",
    "assets",
    "gt_incidents",
    "gt_entities",
    "gt_instruments",
    "gt_assets",
    "entity_matches",
    "instrument_matches",
    "asset_matches",
)

# Evidence tables per incident table, removed when that incident is replaced (the cascade).
_MODEL_CHILDREN = ("entities", "instruments", "assets", "entity_matches", "instrument_matches", "asset_matches")
_GT_CHILDREN = ("gt_entities", "gt_instruments", "gt_assets")


def _coerce(column, value: Any) -> Any:
    """The value a SQL column of this type would hand back for ``value``."""
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, Integer) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return value
        return value
    if isinstance(column_type, Float) and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    if isinstance(column_type, (String, Text)) and not isinstance(value, str):
        return str(value)
    return value


class OfflineEvalStore:
    """In-memory rows keyed like the ``db.py`` tables; never touches a database or the network."""

    backend = "offline"

    def __init__(self) -> None:
        self._rows: dict[str, list[dict]] = {name: [] for name in _TABLES}

    # -- generic row helpers --------------------------------------------- #
    def _row(self, table_name: str, values: dict) -> dict:
        table = db_module.metadata.tables[table_name]
        unknown = set(values) - set(table.columns.keys())
        if unknown:
            raise KeyError(f"{table_name} has no column(s) {sorted(unknown)}")
        return {column.name: _coerce(column, values.get(column.name)) for column in table.columns}

    def _key(self, table_name: str, row: dict) -> tuple:
        table = db_module.metadata.tables[table_name]
        return tuple(row[column.name] for column in table.primary_key.columns)

    def _insert(self, table_name: str, values: dict) -> None:
        row = self._row(table_name, values)
        key = self._key(table_name, row)
        if any(self._key(table_name, existing) == key for existing in self._rows[table_name]):
            raise ValueError(f"duplicate primary key {key!r} in {table_name}")
        self._rows[table_name].append(row)

    def _delete(self, table_name: str, **where: Any) -> None:
        self._rows[table_name] = [
            row for row in self._rows[table_name] if any(row.get(k) != v for k, v in where.items())
        ]

    def _select(self, table_name: str, *, order_by: str | None = None, **where: Any) -> list[dict]:
        rows = [dict(row) for row in self._rows[table_name] if all(row.get(k) == v for k, v in where.items())]
        if order_by is not None:
            rows.sort(key=lambda row: (row[order_by] is None, row[order_by] or ""))
        return rows

    def _first(self, table_name: str, **where: Any) -> dict:
        rows = self._select(table_name, **where)
        return rows[0] if rows else {}

    def healthcheck(self, *, max_age: float = 0.0) -> tuple[bool, str]:
        return True, "offline"

    # -- videos and model runs -------------------------------------------- #
    def upsert_video(
        self, video_id: str, *, filepath: str | None = None, duration: int | None = None, source: str | None = None
    ) -> str:
        existing = self.get_video(video_id)
        self._delete("videos", id=video_id)
        self._insert("videos", {
            "id": video_id, "filepath": filepath, "duration": duration, "source": source,
            "uploaded_datetime": existing.get("uploaded_datetime") or _dt.datetime.now(_dt.UTC).replace(tzinfo=None),
        })
        return video_id

    def get_video(self, video_id: str) -> dict:
        return self._first("videos", id=video_id)

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
        """Insert or update in place; never removes the run's incidents (unlike ``insert_incident``)."""
        self._delete("model_runs", id=model_run_id)
        self._insert("model_runs", {
            "id": model_run_id, "model_name": model_name, "model_version": model_version,
            "prompt_version": prompt_version, "notes": notes,
            "run_datetime": run_datetime or _dt.datetime.now(_dt.UTC).replace(tzinfo=None),
        })
        return model_run_id

    def get_model_run(self, model_run_id: str) -> dict:
        return self._first("model_runs", id=model_run_id)

    # -- model output ------------------------------------------------------ #
    def insert_incident(self, incident_id: str, model_run_id: str, *, fields: dict | None = None) -> tuple[str, str]:
        """Insert or replace one run's incident; its evidence rows and matches go with the old row."""
        payload = {k: (fields or {}).get(k) for k in db_module.IncidentDB._INCIDENT_FIELDS}
        self._delete("incidents", incident_id=incident_id, model_run_id=model_run_id)
        for child in _MODEL_CHILDREN:
            self._delete(child, incident_id=incident_id, model_run_id=model_run_id)
        self._insert("incidents", {"incident_id": incident_id, "model_run_id": model_run_id, **payload})
        return incident_id, model_run_id

    def get_incident(self, incident_id: str, model_run_id: str) -> dict:
        return self._first("incidents", incident_id=incident_id, model_run_id=model_run_id)

    def add_incident_entity(
        self, incident_id: str, model_run_id: str, *, entity_id: str, type: str | None = None,
        description: str | None = None, image: str | None = None,
    ) -> None:
        self._insert("entities", {
            "incident_id": incident_id, "model_run_id": model_run_id, "entity_id": entity_id,
            "type": type, "description": description, "image": image,
        })

    def add_incident_instrument(
        self, incident_id: str, model_run_id: str, *, instrument_id: str, entity_id: str | None = None,
        name: str | None = None, description: str | None = None, threat_level: int | None = None,
        image: str | None = None,
    ) -> None:
        self._insert("instruments", {
            "incident_id": incident_id, "model_run_id": model_run_id, "instrument_id": instrument_id,
            "entity_id": entity_id, "name": name, "description": description, "threat_level": threat_level,
            "image": image,
        })

    def add_incident_asset(
        self, incident_id: str, model_run_id: str, *, asset_id: str, name: str | None = None,
        description: str | None = None, image: str | None = None,
    ) -> None:
        self._insert("assets", {
            "incident_id": incident_id, "model_run_id": model_run_id, "asset_id": asset_id,
            "name": name, "description": description, "image": image,
        })

    def list_incident_entities(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        return self._evidence("entities", "entity_id", incident_id, model_run_id)

    def list_incident_instruments(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        return self._evidence("instruments", "instrument_id", incident_id, model_run_id)

    def list_incident_assets(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        return self._evidence("assets", "asset_id", incident_id, model_run_id)

    def _evidence(self, table_name: str, id_field: str, incident_id: str, model_run_id: str | None) -> list[dict]:
        where: dict[str, Any] = {"incident_id": incident_id}
        if model_run_id is not None:
            where["model_run_id"] = model_run_id
        return self._select(table_name, order_by=id_field, **where)

    # -- ground truth ------------------------------------------------------ #
    def insert_gt_incident(self, incident_id: str, *, fields: dict | None = None) -> str:
        """Insert or replace one GT incident; its GT evidence rows go with the old row."""
        payload = {k: (fields or {}).get(k) for k in db_module.IncidentDB._GT_INCIDENT_FIELDS}
        self._delete("gt_incidents", incident_id=incident_id)
        for child in _GT_CHILDREN:
            self._delete(child, incident_id=incident_id)
        self._insert("gt_incidents", {"incident_id": incident_id, **payload})
        return incident_id

    def get_gt_incident(self, incident_id: str) -> dict:
        return self._first("gt_incidents", incident_id=incident_id)

    def list_gt_incidents(self) -> list[dict]:
        return self._select("gt_incidents", order_by="incident_id")

    def add_gt_entity(
        self, incident_id: str, *, entity_id: str, type: str | None = None,
        description: str | None = None, image: str | None = None,
    ) -> None:
        self._insert("gt_entities", {
            "incident_id": incident_id, "entity_id": entity_id, "type": type, "description": description,
            "image": image,
        })

    def add_gt_instrument(
        self, incident_id: str, *, instrument_id: str, entity_id: str | None = None, name: str | None = None,
        description: str | None = None, threat_level: int | None = None, image: str | None = None,
    ) -> None:
        self._insert("gt_instruments", {
            "incident_id": incident_id, "instrument_id": instrument_id, "entity_id": entity_id, "name": name,
            "description": description, "threat_level": threat_level, "image": image,
        })

    def add_gt_asset(
        self, incident_id: str, *, asset_id: str, name: str | None = None, description: str | None = None,
        image: str | None = None,
    ) -> None:
        self._insert("gt_assets", {
            "incident_id": incident_id, "asset_id": asset_id, "name": name, "description": description,
            "image": image,
        })

    def list_gt_entities(self, incident_id: str) -> list[dict]:
        return self._select("gt_entities", order_by="entity_id", incident_id=incident_id)

    def list_gt_instruments(self, incident_id: str) -> list[dict]:
        return self._select("gt_instruments", order_by="instrument_id", incident_id=incident_id)

    def list_gt_assets(self, incident_id: str) -> list[dict]:
        return self._select("gt_assets", order_by="asset_id", incident_id=incident_id)

    # -- similarity matches (matching.py) ---------------------------------- #
    def record_entity_match(
        self, *, incident_id: str, model_run_id: str, entity_id: str, gt_entity_id: str, similarity_score: float
    ) -> None:
        self._record_match("entity_matches", "entity_id", entity_id, "gt_entity_id", gt_entity_id,
                           incident_id=incident_id, model_run_id=model_run_id, similarity_score=similarity_score)

    def record_instrument_match(
        self, *, incident_id: str, model_run_id: str, instrument_id: str, gt_instrument_id: str,
        similarity_score: float,
    ) -> None:
        self._record_match("instrument_matches", "instrument_id", instrument_id, "gt_instrument_id",
                           gt_instrument_id, incident_id=incident_id, model_run_id=model_run_id,
                           similarity_score=similarity_score)

    def record_asset_match(
        self, *, incident_id: str, model_run_id: str, asset_id: str, gt_asset_id: str, similarity_score: float
    ) -> None:
        self._record_match("asset_matches", "asset_id", asset_id, "gt_asset_id", gt_asset_id,
                           incident_id=incident_id, model_run_id=model_run_id, similarity_score=similarity_score)

    def _record_match(
        self, table_name: str, id_field: str, item_id: str, gt_id_field: str, gt_item_id: str, *,
        incident_id: str, model_run_id: str, similarity_score: float,
    ) -> None:
        self._delete(table_name, incident_id=incident_id, model_run_id=model_run_id, **{id_field: item_id})
        self._insert(table_name, {
            "incident_id": incident_id, "model_run_id": model_run_id, id_field: item_id, gt_id_field: gt_item_id,
            "similarity_score": similarity_score,
            "matched_at": _dt.datetime.now(_dt.UTC).replace(tzinfo=None),
        })

    def list_matches(self, kind: str, incident_id: str, model_run_id: str) -> list[dict]:
        """Recorded matches for ``kind`` (``entities``/``instruments``/``assets``), for inspection and tests."""
        table_name = {"entities": "entity_matches", "instruments": "instrument_matches", "assets": "asset_matches"}[kind]
        id_field = {"entities": "entity_id", "instruments": "instrument_id", "assets": "asset_id"}[kind]
        return self._select(table_name, order_by=id_field, incident_id=incident_id, model_run_id=model_run_id)
