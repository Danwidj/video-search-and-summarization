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

"""Postgres-backed Incident view model.

Presents :class:`db.IncidentDB` rows in the same dict shape ``report_detail`` and
``dashboard_view`` already expect from the offline ``LocalReports`` shim, so the
Report Review and Dashboard pages work against either source unchanged. Unlike
``LocalReports`` (session-only edits over the CSV fixture), every write here
round-trips through Postgres, so field edits, review-status changes and video
re-links survive a page refresh.

Reads go through ``incidents JOIN model_runs JOIN videos`` (``db.py``'s
``list_latest_incidents`` / ``get_latest_incident``): a video is identified with
its incident 1:1 (``incident_id`` == ``videos.id``), and when more than one
model run exists for an incident the most recent run's row is shown - this
adapter does not yet expose a run picker (no new UI screens, per the task).
"""

from __future__ import annotations

from incident_report import timestamp_to_seconds
from r2_videos import configured, playback_url

REVIEW_STATUSES = ["unreviewed", "under review", "verified"]

_FIELD_TO_COLUMN = {
    "incident_type": "type",
    "incident_start": "start_timestamp",
    "incident_end": "end_timestamp",
    "duration": "duration",
    "description": "description",
    "severity": "severity_level",
    "confidence": "confidence_score",
}


def _hhmmss(value) -> str | None:
    """Canonical ``HH:MM:SS`` so downstream ``pd.to_timedelta`` parsing is exact."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    total = timestamp_to_seconds(value)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _basename(filepath) -> str | None:
    if not filepath:
        return None
    return filepath.rsplit("/", 1)[-1]


class DBReports:
    """Read/write incidents through :class:`db.IncidentDB`. Edits persist."""

    supports_db = True

    def __init__(self, db, _state=None):
        self._db = db

    # -- helpers ------------------------------------------------------- #
    def _to_view(self, row: dict) -> dict:
        if not row:
            return {}
        filepath = row.get("video_filepath")
        return {
            "id": row["incident_id"],
            "filename": _basename(filepath),
            "incident_type": row.get("type"),
            "incident_start": row.get("start_timestamp"),
            "incident_end": row.get("end_timestamp"),
            "duration": row.get("duration"),
            "description": row.get("description"),
            "severity": row.get("severity_level"),
            "confidence": row.get("confidence_score"),
            "source": filepath,
            "status": row.get("status") or "unreviewed",
            "model_run_id": row.get("model_run_id"),
            "model_version": row.get("model_version"),
            "video_id": row.get("incident_id"),
            "r2_key": filepath,
            "verified_by": row.get("verified_by"),
            "verified_at": row.get("verified_at"),
            "edited_by": row.get("edited_by"),
            "edited_at": row.get("edited_at"),
        }

    # -- reads ------------------------------------------------------- #
    def list_reports(self, *, incident_type="All", status="All", keyword=None):
        rows = self._db.list_latest_incidents(type_=incident_type, keyword=keyword)
        views = [self._to_view(r) for r in rows]
        if status and status != "All":
            views = [v for v in views if v["status"] == status]
        return views

    def get_report(self, report_id):
        if report_id is None:
            return {}
        return self._to_view(self._db.get_latest_incident(str(report_id)))

    def get_video(self, report_id):
        if report_id is None:
            return {}
        row = self._db.get_latest_incident(str(report_id))
        key = row.get("video_filepath") if row else None
        if not key:
            return {}
        try:
            url = playback_url(key) if configured() else key
        except Exception:
            url = key
        return {
            "ID": f"R2:{row['incident_id']}",
            "Filepath": url,
            "R2_Key": key,
            "filename": _basename(key) or key,
            "Duration": row.get("video_duration"),
        }

    def list_evidence(self, report_id):
        """`{entities, instruments, assets}` rows for the incident's latest run."""
        if report_id is None:
            return {"entities": [], "instruments": [], "assets": []}
        row = self._db.get_latest_incident(str(report_id))
        if not row:
            return {"entities": [], "instruments": [], "assets": []}
        incident_id, model_run_id = row["incident_id"], row["model_run_id"]
        return {
            "entities": self._db.list_incident_entities(incident_id, model_run_id),
            "instruments": self._db.list_incident_instruments(incident_id, model_run_id),
            "assets": self._db.list_incident_assets(incident_id, model_run_id),
        }

    # -- writes (persisted) --------------------------------------- #
    def update_report(self, report_id, *, fields, edited_by=None):
        row = self._db.get_latest_incident(str(report_id)) if report_id is not None else {}
        if not row:
            raise ValueError("Unknown report id")
        payload = dict(fields)
        for key in ("incident_start", "incident_end"):
            if key in payload:
                payload[key] = _hhmmss(payload[key])
        translated = {_FIELD_TO_COLUMN[k]: v for k, v in payload.items() if k in _FIELD_TO_COLUMN}
        self._db.update_incident(row["incident_id"], row["model_run_id"], fields=translated)
        self._db.touch_review_status(row["incident_id"], row["model_run_id"], edited_by=edited_by or "reviewer")

    def set_review_status(self, report_id, *, status, reviewed_by):
        row = self._db.get_latest_incident(str(report_id)) if report_id is not None else {}
        if not row:
            raise ValueError("Unknown report id")
        from config import severity_notify_threshold

        return self._db.set_review_status(
            row["incident_id"],
            row["model_run_id"],
            status=status,
            reviewed_by=reviewed_by,
            notify_threshold=severity_notify_threshold(),
        )

    def link_video(self, report_id, r2_key, *, filename=None, edited_by=None):
        """Point this incident's video row at a different bucket object.

        1 video = 1 incident, so re-linking updates the existing ``videos`` row
        (keyed by the incident id) rather than swapping a foreign key.
        """
        del filename  # videos carries no separate filename column; derived from filepath.
        row = self._db.get_latest_incident(str(report_id)) if report_id is not None else {}
        if not row:
            raise ValueError("Unknown report id")
        self._db.update_video(row["incident_id"], filepath=r2_key or None)
        if edited_by:
            self._db.touch_review_status(row["incident_id"], row["model_run_id"], edited_by=edited_by)
