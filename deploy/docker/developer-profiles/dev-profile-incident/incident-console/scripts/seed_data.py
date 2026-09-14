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

Parses fixtures/data/*.csv (72 sample incident rows on disk: 36 transcribed
from the capstone group's ground-truth sheets, 36 synthetic `SYN-`-prefixed
placeholder rows added to round out category coverage) directly with the
stdlib csv module. The `SYN-`-prefixed rows have no matching video file in the
R2 bucket at all and can never play back, so ``seed_rows()`` drops them before
they reach the importer - only the 36 real, video-backed incidents (and their
joined entities/instruments/assets) are ever seeded. This is the only
consumer of the CSV fixture - the offline CSV-preview UI mode
(fixtures/dashboard_seed.py, local_reports.py, pages/1_Catalog.py,
pages/4_Severity_Eval.py) has been removed; the console is database-backed
only. All seeded incidents share one model_run_id (MR-SEED), representing one
hypothetical model pass over the fixture videos, not many separate runs.

Known ground-truth gap (carried through as-is, not invented): entities.csv
carries one stray row, RoadAccidents006/E2, with no matching incidents.csv row
of its own; it links to no incident. scripts/seed_supabase.py skips it rather
than violating the entities->incidents foreign key.

Filepath / R2 key derivation: each incident's ``Filename`` is deterministically
mapped to its real object key in the ``anomaly-detection-dataset`` R2 bucket,
``anomaly/<category-folder>/<filename>`` - the exact clip that filename names,
never a different clip substituted in from the same category (verified live
against the bucket; see the PR description for the incident_id -> R2 key
spot-checks). The category folder is derived from the filename's own prefix
(``Animal`` / ``Burglary`` / ``Explosion`` / ``Fighting`` / ``RoadAccident(s)``,
with or without the ``SYN-`` prefix used by the 36 generated rows) rather than
the CSV ``Type`` column, because 3 rows (Burglary005/006, Explosion007) carry a
blank ``Type`` but a normally-named, real-backed ``Filename``.

Known content gap (not fixed here - would require new source video, out of
scope): the 36 ``SYN-*`` filenames are fabricated placeholders invented to pad
the fixture out to 72 rows (see the module docstring above) and have no
matching object in the bucket - the exact key is still written (so a future
upload with that exact name starts working immediately with no seed change),
but it will not resolve to a playable clip today. This is every ``fighting``
row (all 12 are ``SYN-Fighting*``) plus a handful in each other category.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "data"

MODEL_RUN_ID = "MR-SEED"
MODEL_NAME = "csv-fixture-seed"
MODEL_VERSION = None
PROMPT_VERSION = "v1"
SYNTHETIC_INCIDENT_PREFIX = "SYN-"

# R2 bucket layout, verified live against `anomaly-detection-dataset` (listed
# via boto3 `list_objects_v2` on the `anomaly/` prefix): category folder names
# don't always match the CSV `Type` column spelling (e.g. `animal` -> the
# `animal_attacks/` folder, `road accident` -> `road_accidents/`), and one
# (`fighting`) has no `Type`-column counterpart naming collision to worry about
# since it's keyed off the filename prefix instead - see module docstring.
_CATEGORY_FOLDERS = {
    "animal": "animal_attacks",
    "burglary": "burglary",
    "explosion": "explosion",
    "fighting": "fighting",
    "roadaccident": "road_accidents",
    "roadaccidents": "road_accidents",
}

_PREFIX_RE = re.compile(r"^([A-Za-z]+)")


def _r2_key(filename: str) -> str:
    """The real bucket object key this filename names: ``anomaly/<folder>/<filename>``."""
    base = filename.removeprefix("SYN-")
    match = _PREFIX_RE.match(base)
    prefix = match.group(1).lower() if match else ""
    folder = _CATEGORY_FOLDERS.get(prefix)
    if folder is None:
        raise ValueError(f"seed_data: no known R2 category folder for filename {filename!r}")
    return f"anomaly/{folder}/{filename}"


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
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


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
        if incident_id.startswith(SYNTHETIC_INCIDENT_PREFIX):
            continue
        filename = source["Filename"]
        start = _int(source["Start_Timestamp_sec"])
        end = _int(source["End_Timestamp_sec"])
        duration = _int(source["Duration_sec"])
        incidents.append(
            {
                "Incident_ID": incident_id,
                "Model_Run_ID": MODEL_RUN_ID,
                "Filename": filename,
                "Filepath": _r2_key(filename),
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
