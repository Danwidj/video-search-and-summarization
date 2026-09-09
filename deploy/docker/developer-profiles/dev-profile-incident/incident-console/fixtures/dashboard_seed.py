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

"""Review fixtures parsed from committed CSVs. Never imported by the database layer.

`data/` holds four CSV files with 72 sample incidents (36 transcribed from the
capstone group's ground-truth sheets, 36 with `SYN-` prefixed IDs generated to
fill gaps the sheets lack). `load_seed()` parses them with the stdlib
:mod:`csv` module and returns the same dict shape the previous hardcoded
fixture returned, so every consumer keeps working unchanged.

Timestamps are emitted as video-relative ``HH:MM:SS`` strings; Duration is an int
number of seconds; Confidence_Score is 0-1 and is omitted entirely when absent.
All URLs are opaque, deliberately non-resolving placeholders on example.invalid.
IDs are local to an incident for entities/instruments/assets; joins include
Incident_ID. See fixtures/README.md for the composition notes and the
known-gap list carried over from the ground-truth NOTES.
"""

import contextlib
import csv
import os
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def _text(value):
    """Trimmed string, or None when the cell is blank."""
    value = (value or "").strip()
    return value or None


def _int(value):
    """Int value, or None when the cell is blank (blanks stay missing, not 0)."""
    value = (value or "").strip()
    return int(value) if value else None


def _float(value):
    value = (value or "").strip()
    return float(value) if value else None


def _timestamp(seconds):
    if seconds is None:
        return None
    return f"00:{seconds // 60:02d}:{seconds % 60:02d}"


def _rows(name):
    with (DATA_DIR / name).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def update_incident(incident_id, values):
    """Persist editable Incident fields back to the committed CSV.

    The CSV is the local source of truth for the fixture preview. Only columns
    already present in incidents.csv can be changed; IDs and filenames remain
    stable join keys for the related tables and videos.
    """
    path = DATA_DIR / "incidents.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    allowed = {
        "Type",
        "Start_Timestamp_sec",
        "End_Timestamp_sec",
        "Duration_sec",
        "Description",
        "Severity_Level",
        "Confidence_Score",
    }
    updates = {key: value for key, value in values.items() if key in allowed}
    found = False
    for row in rows:
        if row.get("Incident_ID") == incident_id:
            row.update({key: "" if value is None else str(value) for key, value in updates.items()})
            found = True
            break
    if not found:
        raise KeyError(f"Unknown Incident_ID: {incident_id}")
    fd, temporary = tempfile.mkstemp(prefix="incidents-", suffix=".csv", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def load_seed():
    data = {name: [] for name in ("Incident", "Entity", "Instrument", "Asset", "Report", "Video", "Query")}

    for n, source in enumerate(_rows("incidents.csv"), 1):
        incident_id = source["Incident_ID"]
        filename = source["Filename"]
        start = _int(source["Start_Timestamp_sec"])
        end = _int(source["End_Timestamp_sec"])
        duration = _int(source["Duration_sec"])
        url = f"https://media.example.invalid/seed/{incident_id}"
        row = {
            "Filename": filename,
            "Incident_ID": incident_id,
            "Type": _text(source["Type"]),
            "Start_Timestamp": _timestamp(start),
            "End_Timestamp": _timestamp(end),
            "Duration": duration,
            "Description": _text(source["Description"]),
            "Severity": _int(source["Severity_Level"]),
            "Source": f"{url}/source",
        }
        confidence = _float(source["Confidence_Score"])
        if confidence is not None:
            row["Confidence_Score"] = confidence
        data["Incident"].append(row)
        data["Video"].append(
            {
                "ID": f"V{n}",
                "Incident_ID": incident_id,
                "Filename": filename,
                "Filepath": f"{url}/{filename}",
                "Uploaded_DateTime": "2026-09-01T09:00:00Z",
                "Duration": (start or 0) + (duration or 0) + 5,
                "Source": f"{url}/source",
            }
        )

    for source in _rows("entities.csv"):
        data["Entity"].append(
            {
                "Filename": source["Filename"],
                "Incident_ID": source["Incident_ID"],
                "ID": source["ID"],
                "Type": _text(source["Type"]),
                "Description": _text(source["Description"]),
                "Image": None,
            }
        )

    for source in _rows("instruments.csv"):
        data["Instrument"].append(
            {
                "Filename": source["Filename"],
                "Incident_ID": source["Incident_ID"],
                "Entity_ID": _text(source["Entity_ID"]),
                "ID": source["ID"],
                "Name": _text(source["Name"]),
                "Description": _text(source["Description"]),
                "Threat_Level": _int(source["Threat_Level"]),
                "Image": None,
            }
        )

    for source in _rows("assets.csv"):
        data["Asset"].append(
            {
                "Filename": source["Filename"],
                "Incident_ID": source["Incident_ID"],
                "ID": source["ID"],
                "Name": _text(source["Name"]),
                "Description": _text(source["Description"]),
                "Image": None,
            }
        )

    return data
