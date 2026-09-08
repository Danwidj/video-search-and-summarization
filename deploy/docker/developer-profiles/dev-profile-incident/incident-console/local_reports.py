"""CSV-backed Incident view model used by the report page."""

from copy import deepcopy

from fixtures.dashboard_seed import load_seed, update_incident
from r2_videos import configured, list_video_keys, map_incidents_to_video_keys, playback_url


def _seconds(value):
    if value is None:
        return None
    parts = str(value).split(":")
    try:
        values = [int(part) for part in parts]
    except ValueError:
        return None
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return values[0] * 60 + values[1]
    if len(values) == 3:
        return values[0] * 3600 + values[1] * 60 + values[2]
    return None


def _report(row):
    return {
        "id": row["Incident_ID"],
        "filename": row["Filename"],
        "incident_type": row["Type"],
        "incident_start": row["Start_Timestamp"],
        "incident_end": row["End_Timestamp"],
        "duration": row["Duration"],
        "description": row["Description"],
        "severity": row["Severity"],
        "confidence": row.get("Confidence_Score"),
        "source": row["Source"],
        "synthetic": row["synthetic"],
    }


class LocalReports:
    """Read committed CSV rows and persist edits atomically to incidents.csv."""

    def __init__(self, _state=None):
        self._seed = load_seed()
        self._reports = [_report(row) for row in self._seed["Incident"]]
        self._video_keys = {}
        if configured():
            try:
                self._video_keys = map_incidents_to_video_keys(self._seed["Incident"], list_video_keys())
            except Exception:
                self._video_keys = {}

    def list_reports(self, *, incident_type="All", status="All", keyword=None):
        del status  # Status is not a field in fixtures/data/incidents.csv.
        rows = self._reports
        if incident_type and incident_type != "All":
            rows = [row for row in rows if row["incident_type"] == incident_type]
        if keyword:
            query = keyword.casefold()
            rows = [
                row
                for row in rows
                if query
                in " ".join(
                    str(row.get(key) or "") for key in ("id", "filename", "incident_type", "description")
                ).casefold()
            ]
        return deepcopy(rows)

    def get_report(self, report_id):
        return deepcopy(next((row for row in self._reports if row["id"] == report_id), {}))

    def get_video(self, report_id):
        key = self._video_keys.get(report_id)
        if not key:
            return {}
        try:
            url = playback_url(key)
        except Exception:
            url = key
        report = self.get_report(report_id)
        start = _seconds(report.get("incident_start")) or 0
        duration = _seconds(report.get("duration"))
        return {
            "ID": f"R2:{report_id}",
            "Filepath": url,
            "R2_Key": key,
            "filename": key,
            "Duration": (start + duration + 5) if duration is not None else None,
        }

    def update_report(self, report_id, *, fields, edited_by=None):
        del edited_by  # Attribution is not a field in the supplied CSV schema.
        start = _seconds(fields.get("incident_start"))
        end = _seconds(fields.get("incident_end"))
        update_incident(
            report_id,
            {
                "Type": fields.get("incident_type"),
                "Start_Timestamp_sec": start,
                "End_Timestamp_sec": end,
                "Duration_sec": end - start if start is not None and end is not None and end >= start else None,
                "Description": fields.get("description"),
                "Severity_Level": fields.get("severity"),
                "Confidence_Score": fields.get("confidence"),
            },
        )

    def link_video(self, report_id, url):
        del report_id, url
        raise ValueError("Video links are derived from the incident Filename and R2 inventory.")
