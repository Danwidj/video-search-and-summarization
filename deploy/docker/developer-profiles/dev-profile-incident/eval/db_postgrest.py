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

"""Minimal Supabase PostgREST-backed adapter, for environments where direct
Postgres (``db.py``'s ``IncidentDB``, port 5432/6543) is network-blocked but
HTTPS (443) is reachable.

Additive, not a replacement: ``db.py`` stays the primary, fully-tested
direct-Postgres path. This implements only the subset of ``IncidentDB``'s
method surface the P1/RP1 multi-model evaluation actually calls (GT
ingestion, ``matching.py``, ``eval_gt.py``, and the batch evaluation runner),
with identical method signatures and return shapes, over the same tables and
column names - so ``eval_gt.run_evaluation(db, ...)`` and
``matching.match_incident(db, ...)`` work unchanged against either backend
(duck typing, not inheritance - no import of ``db.py`` here).

Verified against the real project by hand before any bulk write: a throwaway
insert/read/delete round-trip on ``videos``/``gt_incidents`` behaved
identically to the direct-Postgres path's schema (same columns, same insert/
read/delete semantics, HTTP 201/200/204 as expected).
"""

from __future__ import annotations

import os
from datetime import datetime

import httpx


class PostgrestError(RuntimeError):
    """A PostgREST call returned a non-2xx status."""


def _clean(value: str | None) -> str:
    return (value or "").strip()


def configured() -> bool:
    return bool(_clean(os.getenv("INCIDENT_SUPABASE_URL"))) and bool(
        _clean(os.getenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY"))
    )


class PostgrestIncidentDB:
    """Supabase PostgREST client exposing the ``IncidentDB`` methods this eval needs."""

    def __init__(self, base_url: str | None = None, service_role_key: str | None = None, *, timeout: float = 30.0):
        self.base_url = (base_url or _clean(os.getenv("INCIDENT_SUPABASE_URL"))).rstrip("/")
        self.key = service_role_key or _clean(os.getenv("INCIDENT_SUPABASE_SERVICE_ROLE_KEY"))
        if not self.base_url or not self.key:
            raise RuntimeError("INCIDENT_SUPABASE_URL / INCIDENT_SUPABASE_SERVICE_ROLE_KEY not configured")
        self._client = httpx.Client(
            base_url=f"{self.base_url}/rest/v1",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    # -- low-level REST helpers ------------------------------------------ #

    def _get(self, table: str, params: dict) -> list[dict]:
        resp = self._client.get(f"/{table}", params=params)
        if resp.status_code >= 400:
            raise PostgrestError(f"GET {table} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _post(self, table: str, rows: list[dict] | dict, *, upsert_on: str | None = None) -> list[dict]:
        headers = {"Prefer": "return=representation" + (",resolution=merge-duplicates" if upsert_on else "")}
        params = {"on_conflict": upsert_on} if upsert_on else None
        resp = self._client.post(f"/{table}", json=rows, headers=headers, params=params)
        if resp.status_code >= 400:
            raise PostgrestError(f"POST {table} -> {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _delete(self, table: str, params: dict) -> None:
        resp = self._client.delete(f"/{table}", params=params)
        if resp.status_code >= 400:
            raise PostgrestError(f"DELETE {table} -> {resp.status_code}: {resp.text[:500]}")

    def _rpc(self, function_name: str, params: dict) -> None:
        resp = self._client.post(f"/rpc/{function_name}", json=params)
        if resp.status_code >= 400:
            raise PostgrestError(f"RPC {function_name} -> {resp.status_code}: {resp.text[:500]}")

    def _get_one(self, table: str, params: dict) -> dict:
        rows = self._get(table, {**params, "limit": 1})
        return rows[0] if rows else {}

    # -- videos ------------------------------------------------------------ #

    def upsert_video(self, video_id: str, *, filepath: str | None = None, duration: int | None = None,
                      source: str | None = None) -> str:
        self._post(
            "videos",
            {"id": video_id, "filepath": filepath, "duration": duration, "source": source},
            upsert_on="id",
        )
        return video_id

    def get_video(self, video_id: str) -> dict:
        return self._get_one("videos", {"id": f"eq.{video_id}"})

    # -- ground truth: incidents -------------------------------------------- #

    _GT_INCIDENT_FIELDS = (
        "type", "start_timestamp", "end_timestamp", "duration", "description",
        "severity_level", "labelled_by", "labelled_datetime",
    )

    def insert_gt_incident(self, incident_id: str, *, fields: dict | None = None) -> str:
        payload = {k: (fields or {}).get(k) for k in self._GT_INCIDENT_FIELDS}
        for key, value in payload.items():
            if isinstance(value, datetime):
                payload[key] = value.isoformat()
        # Delete-then-insert, matching IncidentDB.insert_gt_incident's semantics
        # (cascades away old gt_entities/gt_instruments/gt_assets for this id).
        self._delete("gt_incidents", {"incident_id": f"eq.{incident_id}"})
        self._post("gt_incidents", {"incident_id": incident_id, **payload})
        return incident_id

    def get_gt_incident(self, incident_id: str) -> dict:
        return self._get_one("gt_incidents", {"incident_id": f"eq.{incident_id}"})

    def add_gt_entity(self, incident_id: str, *, entity_id: str, type: str | None = None,
                       description: str | None = None, image: str | None = None) -> None:
        self._post(
            "gt_entities",
            {"incident_id": incident_id, "entity_id": entity_id, "type": type, "description": description, "image": image},
        )

    def add_gt_instrument(self, incident_id: str, *, instrument_id: str, entity_id: str | None = None,
                           name: str | None = None, description: str | None = None,
                           threat_level: int | None = None, image: str | None = None) -> None:
        self._post(
            "gt_instruments",
            {
                "incident_id": incident_id, "instrument_id": instrument_id, "entity_id": entity_id,
                "name": name, "description": description, "threat_level": threat_level, "image": image,
            },
        )

    def add_gt_asset(self, incident_id: str, *, asset_id: str, name: str | None = None,
                      description: str | None = None, image: str | None = None) -> None:
        self._post(
            "gt_assets",
            {"incident_id": incident_id, "asset_id": asset_id, "name": name, "description": description, "image": image},
        )

    def list_gt_entities(self, incident_id: str) -> list[dict]:
        return self._get("gt_entities", {"incident_id": f"eq.{incident_id}", "order": "entity_id"})

    def list_gt_instruments(self, incident_id: str) -> list[dict]:
        return self._get("gt_instruments", {"incident_id": f"eq.{incident_id}", "order": "instrument_id"})

    def list_gt_assets(self, incident_id: str) -> list[dict]:
        return self._get("gt_assets", {"incident_id": f"eq.{incident_id}", "order": "asset_id"})

    # -- model runs and model-produced incidents ---------------------------- #

    def insert_model_run(self, model_run_id: str, *, model_name: str, model_version: str | None = None,
                          prompt_version: str | None = None, run_datetime: datetime | None = None,
                          notes: str | None = None) -> str:
        payload = {
            "id": model_run_id, "model_name": model_name, "model_version": model_version,
            "prompt_version": prompt_version, "notes": notes,
        }
        if run_datetime is not None:
            payload["run_datetime"] = run_datetime.isoformat()
        self._post("model_runs", payload, upsert_on="id")
        return model_run_id

    _INCIDENT_FIELDS = (
        "type", "start_timestamp", "end_timestamp", "duration", "description",
        "severity_level", "confidence_score",
    )

    def insert_incident(self, incident_id: str, model_run_id: str, *, fields: dict | None = None) -> tuple[str, str]:
        fields = fields or {}
        params = {
            "p_incident_id": incident_id,
            "p_model_run_id": model_run_id,
            **{f"p_{k}": fields.get(k) for k in self._INCIDENT_FIELDS},
        }
        self._rpc("insert_incident", params)
        return incident_id, model_run_id

    def get_incident(self, incident_id: str, model_run_id: str) -> dict:
        return self._get_one("incidents", {"incident_id": f"eq.{incident_id}", "model_run_id": f"eq.{model_run_id}"})

    def add_incident_entity(self, incident_id: str, model_run_id: str, *, entity_id: str, type: str | None = None,
                             description: str | None = None, image: str | None = None) -> None:
        self._post(
            "entities",
            {
                "incident_id": incident_id, "model_run_id": model_run_id, "entity_id": entity_id,
                "type": type, "description": description, "image": image,
            },
        )

    def add_incident_instrument(self, incident_id: str, model_run_id: str, *, instrument_id: str,
                                 entity_id: str | None = None, name: str | None = None,
                                 description: str | None = None, threat_level: int | None = None,
                                 image: str | None = None) -> None:
        self._post(
            "instruments",
            {
                "incident_id": incident_id, "model_run_id": model_run_id, "instrument_id": instrument_id,
                "entity_id": entity_id, "name": name, "description": description,
                "threat_level": threat_level, "image": image,
            },
        )

    def add_incident_asset(self, incident_id: str, model_run_id: str, *, asset_id: str, name: str | None = None,
                            description: str | None = None, image: str | None = None) -> None:
        self._post(
            "assets",
            {
                "incident_id": incident_id, "model_run_id": model_run_id, "asset_id": asset_id,
                "name": name, "description": description, "image": image,
            },
        )

    def list_incident_entities(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        params = {"incident_id": f"eq.{incident_id}", "order": "entity_id"}
        if model_run_id is not None:
            params["model_run_id"] = f"eq.{model_run_id}"
        return self._get("entities", params)

    def list_incident_instruments(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        params = {"incident_id": f"eq.{incident_id}", "order": "instrument_id"}
        if model_run_id is not None:
            params["model_run_id"] = f"eq.{model_run_id}"
        return self._get("instruments", params)

    def list_incident_assets(self, incident_id: str, model_run_id: str | None = None) -> list[dict]:
        params = {"incident_id": f"eq.{incident_id}", "order": "asset_id"}
        if model_run_id is not None:
            params["model_run_id"] = f"eq.{model_run_id}"
        return self._get("assets", params)

    # -- similarity match persistence (matching.py) -------------------------- #

    def record_entity_match(self, *, incident_id: str, model_run_id: str, entity_id: str, gt_entity_id: str,
                             similarity_score: float) -> None:
        self._delete(
            "entity_matches",
            {"incident_id": f"eq.{incident_id}", "model_run_id": f"eq.{model_run_id}", "entity_id": f"eq.{entity_id}"},
        )
        self._post(
            "entity_matches",
            {
                "incident_id": incident_id, "model_run_id": model_run_id, "entity_id": entity_id,
                "gt_entity_id": gt_entity_id, "similarity_score": similarity_score,
            },
        )

    def record_instrument_match(self, *, incident_id: str, model_run_id: str, instrument_id: str,
                                 gt_instrument_id: str, similarity_score: float) -> None:
        self._delete(
            "instrument_matches",
            {
                "incident_id": f"eq.{incident_id}", "model_run_id": f"eq.{model_run_id}",
                "instrument_id": f"eq.{instrument_id}",
            },
        )
        self._post(
            "instrument_matches",
            {
                "incident_id": incident_id, "model_run_id": model_run_id, "instrument_id": instrument_id,
                "gt_instrument_id": gt_instrument_id, "similarity_score": similarity_score,
            },
        )

    def record_asset_match(self, *, incident_id: str, model_run_id: str, asset_id: str, gt_asset_id: str,
                            similarity_score: float) -> None:
        self._delete(
            "asset_matches",
            {"incident_id": f"eq.{incident_id}", "model_run_id": f"eq.{model_run_id}", "asset_id": f"eq.{asset_id}"},
        )
        self._post(
            "asset_matches",
            {
                "incident_id": incident_id, "model_run_id": model_run_id, "asset_id": asset_id,
                "gt_asset_id": gt_asset_id, "similarity_score": similarity_score,
            },
        )
