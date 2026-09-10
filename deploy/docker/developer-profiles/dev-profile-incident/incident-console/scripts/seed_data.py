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

"""CSV-backed seed data source for the Postgres importer.

Parses fixtures/data/*.csv (72 sample incidents: 36 transcribed from the
capstone group's ground-truth sheets, 36 generated to fill gaps) directly with
the stdlib csv module. This is the only consumer of the CSV fixture - the
offline CSV-preview UI mode (fixtures/dashboard_seed.py, local_reports.py,
pages/1_Catalog.py, pages/4_Severity_Eval.py) has been removed; the console is
database-backed only. All 72 incidents are seeded under one shared
model_run_id (MR-SEED), representing one hypothetical model pass over the
fixture videos, not 72 separate runs.

Known ground-truth gap (carried through as-is, not invented): entities.csv
carries one stray row, RoadAccidents006/E2, with no matching incidents.csv row
of its own; it links to no incident. scripts/seed_supabase.py skips it rather
than violating the entities->incidents foreign key.
"""

from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "data"

MODEL_RUN_ID = "MR-SEED"
MODEL_NAME = "csv-fixture-seed"
MODEL_VERSION = None
PROMPT_VERSION = "v1"


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


def seed_rows() -> dict:
    """``{"Incident": [...], "Entity": [...], "Instrument": [...], "Asset": [...]}``

    Each ``Incident`` row also carries ``Filepath``/``Video_Duration`` for the
    matching ``videos`` row (1 video = 1 incident, so no separate Video list).
    """
    incidents = []
    for source in _rows("incidents.csv"):
        incident_id = source["Incident_ID"]
        filename = source["Filename"]
        start = _int(source["Start_Timestamp_sec"])
        end = _int(source["End_Timestamp_sec"])
        duration = _int(source["Duration_sec"])
        url = f"https://media.example.invalid/seed/{incident_id}"
        incidents.append(
            {
                "Incident_ID": incident_id,
                "Model_Run_ID": MODEL_RUN_ID,
                "Filename": filename,
                "Filepath": f"{url}/{filename}",
                "Video_Duration": (start or 0) + (duration or 0) + 5,
                "Type": _text(source["Type"]),
                "Start_Timestamp": _timestamp(start),
                "End_Timestamp": _timestamp(end),
                "Duration": duration,
                "Description": _text(source["Description"]),
                "Severity": _int(source["Severity_Level"]),
                "Confidence_Score": _float(source["Confidence_Score"]),
            }
        )

    entities = [
        {
            "Incident_ID": source["Incident_ID"],
            "Model_Run_ID": MODEL_RUN_ID,
            "ID": source["ID"],
            "Type": _text(source["Type"]),
            "Description": _text(source["Description"]),
        }
        for source in _rows("entities.csv")
    ]
    instruments = [
        {
            "Incident_ID": source["Incident_ID"],
            "Model_Run_ID": MODEL_RUN_ID,
            "Entity_ID": _text(source["Entity_ID"]),
            "ID": source["ID"],
            "Name": _text(source["Name"]),
            "Description": _text(source["Description"]),
            "Threat_Level": _int(source["Threat_Level"]),
        }
        for source in _rows("instruments.csv")
    ]
    assets = [
        {
            "Incident_ID": source["Incident_ID"],
            "Model_Run_ID": MODEL_RUN_ID,
            "ID": source["ID"],
            "Name": _text(source["Name"]),
            "Description": _text(source["Description"]),
        }
        for source in _rows("assets.csv")
    ]
    return {"Incident": incidents, "Entity": entities, "Instrument": instruments, "Asset": assets}
