"""Session-local review adapter over the dashboard's unchanged seed fixture.

Only explicitly linked video URLs leave the browser. No database or R2 metadata
reads/writes; report edits and review state last for the current app session.
"""

from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import urlparse

from fixtures.dashboard_seed import load_seed


class LocalReports:
    def __init__(self, state):
        self.state = state
        if "local_incident_reports" not in state:
            state["local_incident_reports"] = {
                row["Incident_ID"]: {
                    "id": row["Incident_ID"],
                    "incident_type": row["Type"],
                    "incident_start": row["Start_Timestamp"],
                    "incident_end": row["End_Timestamp"],
                    "duration": row["Duration"],
                    "description": row["Description"],
                    "severity": row["Severity"],
                    "confidence": row.get("Confidence_Score"),
                    "filename": row["Filename"],
                    "status": "unreviewed",
                }
                for row in load_seed()["Incident"]
            }
        if "local_incident_videos" not in state:
            state["local_incident_videos"] = {}

    def list_reports(self, *, incident_type="All", status="All", keyword=None):
        return [
            deepcopy(r)
            for r in self.state["local_incident_reports"].values()
            if (incident_type == "All" or r["incident_type"] == incident_type)
            and (status == "All" or r["status"] == status)
            and (
                not keyword
                or keyword.casefold()
                in " ".join(str(r.get(k) or "") for k in ("id", "incident_type", "description", "filename")).casefold()
            )
        ]

    def get_report(self, report_id):
        return deepcopy(self.state["local_incident_reports"].get(report_id, {}))

    def get_video(self, report_id):
        return deepcopy(self.state["local_incident_videos"].get(report_id, {}))

    def link_video(self, report_id, url):
        if report_id not in self.state["local_incident_reports"]:
            raise ValueError("Incident not found")
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Enter a complete HTTP or HTTPS video URL.")
        self.state["local_incident_videos"][report_id] = {"Filepath": url}

    def update_report(self, report_id, *, fields, edited_by):
        from report_detail import seconds

        row = self.state["local_incident_reports"][report_id]
        row.update(fields)
        start, end = seconds(row["incident_start"]), seconds(row["incident_end"])
        row["duration"] = end - start if start is not None and end is not None and end >= start else None
        row.update(edited_by=edited_by, edited_at=datetime.now(UTC).isoformat())

    def set_report_review_status(self, report_id, *, status, reviewed_by, notify_threshold=None):
        if status not in {"verified", "under review", "unreviewed"} or not reviewed_by.strip():
            raise ValueError("A valid status and reviewer are required")
        row = self.state["local_incident_reports"][report_id]
        now = datetime.now(UTC).isoformat()
        row.update(
            status=status,
            edited_by=reviewed_by,
            edited_at=now,
            verified_by=reviewed_by if status == "verified" else None,
            verified_at=now if status == "verified" else None,
        )
        return {"notified": False, "severity": row["severity"]}
