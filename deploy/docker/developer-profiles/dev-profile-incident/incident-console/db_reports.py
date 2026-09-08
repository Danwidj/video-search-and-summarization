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
round-trips through Supabase, so field edits, review-status changes and video
re-links survive a page refresh.
"""

from __future__ import annotations

from incident_report import timestamp_to_seconds
from r2_videos import configured, playback_url

REVIEW_STATUSES = ["unreviewed", "under review", "verified"]


def _hhmmss(value) -> str | None:
    """Canonical ``HH:MM:SS`` so downstream ``pd.to_timedelta`` parsing is exact."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    total = timestamp_to_seconds(value)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class DBReports:
    """Read/write incidents through :class:`db.IncidentDB`. Edits persist."""

    supports_db = True

    def __init__(self, db, _state=None):
        self._db = db
        self._videos: dict[int, dict] = {}

    # -- helpers ------------------------------------------------------- #
    @staticmethod
    def _coerce_id(report_id) -> int | None:
        try:
            return int(report_id)
        except (TypeError, ValueError):
            return None

    def _video_row(self, video_id) -> dict:
        if not video_id:
            return {}
        if video_id not in self._videos:
            self._videos[video_id] = self._db.get_video(int(video_id)) or {}
        return self._videos[video_id]

    def _to_view(self, row: dict) -> dict:
        if not row:
            return {}
        video = self._video_row(row.get("video_id"))
        duration = row.get("duration_sec")
        if duration is None:
            start = timestamp_to_seconds(row.get("incident_start"))
            end = timestamp_to_seconds(row.get("incident_end"))
            duration = end - start if end >= start else None
        return {
            "id": row["id"],
            "filename": video.get("filename") or video.get("r2_key"),
            "incident_type": row.get("incident_type"),
            "incident_start": row.get("incident_start"),
            "incident_end": row.get("incident_end"),
            "incident_start_confirmed": row.get("incident_start_confirmed"),
            "duration": duration,
            "description": row.get("description"),
            "severity": row.get("severity"),
            "confidence": row.get("confidence"),
            "source": video.get("r2_key"),
            "status": row.get("status"),
            "is_synthetic": row.get("is_synthetic"),
            "model_version": row.get("model_version"),
            "video_id": row.get("video_id"),
            "r2_key": video.get("r2_key"),
        }

    # -- reads ------------------------------------------------------- #
    def list_reports(self, *, incident_type="All", status="All", keyword=None):
        rows = self._db.list_reports(incident_type=incident_type, status=status, keyword=keyword)
        return [self._to_view(r) for r in rows]

    def get_report(self, report_id):
        rid = self._coerce_id(report_id)
        if rid is None:
            return {}
        return self._to_view(self._db.get_report(rid))

    def get_video(self, report_id):
        rid = self._coerce_id(report_id)
        if rid is None:
            return {}
        report = self._db.get_report(rid)
        video = self._video_row(report.get("video_id")) if report else {}
        key = video.get("r2_key")
        if not key:
            return {}
        try:
            url = playback_url(key) if configured() else key
        except Exception:
            url = key
        return {
            "ID": f"R2:{video['id']}",
            "Filepath": url,
            "R2_Key": key,
            "filename": video.get("filename") or key,
            "Duration": video.get("duration_sec"),
        }

    def list_evidence(self, report_id):
        """`{entities, instruments, assets}` rows for the report, DB order."""
        rid = self._coerce_id(report_id)
        if rid is None:
            return {"entities": [], "instruments": [], "assets": []}
        return {
            "entities": self._db.list_incident_entities(rid),
            "instruments": self._db.list_incident_instruments(rid),
            "assets": self._db.list_incident_assets(rid),
        }

    # -- writes (persisted) --------------------------------------- #
    def update_report(self, report_id, *, fields, edited_by=None):
        rid = self._coerce_id(report_id)
        if rid is None:
            raise ValueError("Unknown report id")
        payload = dict(fields)
        for key in ("incident_start", "incident_end"):
            if key in payload:
                payload[key] = _hhmmss(payload[key])
        self._db.update_report(rid, fields=payload, edited_by=(edited_by or "reviewer"))

    def set_review_status(self, report_id, *, status, reviewed_by):
        rid = self._coerce_id(report_id)
        if rid is None:
            raise ValueError("Unknown report id")
        from config import severity_notify_threshold

        return self._db.set_report_review_status(
            rid, status=status, reviewed_by=reviewed_by, notify_threshold=severity_notify_threshold()
        )

    def link_video(self, report_id, r2_key, *, filename=None, edited_by=None):
        """Point the incident at a different bucket object; persist the FK."""
        rid = self._coerce_id(report_id)
        if rid is None:
            raise ValueError("Unknown report id")
        if not r2_key:
            self._db.link_report_video(rid, None, edited_by=edited_by)
            self._videos.clear()
            return
        existing = self._db.get_video_by_r2_key(r2_key)
        if existing:
            video_id = existing["id"]
        else:
            video_id = self._db.insert_video(
                filename=filename or r2_key.rsplit("/", 1)[-1], r2_key=r2_key, status="analyzed"
            )
        self._db.link_report_video(rid, video_id, edited_by=edited_by)
        self._videos.clear()
