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

"""Import the real (not demo) GT workbook into gt_incidents/gt_entities/gt_instruments/gt_assets.

Source: ``eval_data/ground_truth_labelling.xlsx`` (gitignored, real data - see
``prompts.py`` and ``scripts/eval_video_resolution.py`` for the rest of the
P1/RP1 multi-model evaluation this feeds). Mirrors the layout
``fixtures/data/*.csv`` / ``scripts/seed_data.py`` already use for the demo
seed, but reads the real workbook's own sheets directly rather than going
through an intermediate CSV.

Applies the three fixes identified while inspecting the workbook (see the
eval-workflow plan):
1. ``gt_incidents`` has 1015 raw rows but only 80 are real data - the rest are
   empty except a stray ``0`` in the Duration column (an Excel formatting
   artifact). Filtered by requiring a non-empty ``Type``.
2. The GT label ``Animal`` is renamed to ``Animal Attack`` here so it reads
   identically to P1's own permitted value (P1 says "animal attack"; every
   other category already matches P1 after case-folding).
3. ``gt_entities``/``gt_instruments``/``gt_assets`` are read by explicit
   column name only - this naturally drops the two ``gt_assets`` rows'
   (Burglary004, Burglary005) stray trailing cells past the documented
   ``Image`` column without special-casing them.

``Labelled_DateTime`` is an Excel serial date number in the source sheet, not
a formatted string - converted to a real ``datetime`` here, not copied as-is.

Idempotent: ``insert_gt_incident`` deletes-then-inserts the ``gt_incidents``
row, and ``ON DELETE CASCADE`` on ``gt_entities``/``gt_instruments``/
``gt_assets`` clears their old rows for that incident before this script adds
the fresh ones - safe to re-run.

Usage (from this directory, with the venv active)::

    .venv/bin/python3 scripts/eval_ingest_gt.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import openpyxl  # noqa: E402

import config  # noqa: F401,E402  loads the app environment before db reads it
import db as db_module  # noqa: E402
from db_postgrest import PostgrestIncidentDB  # noqa: E402
from db_postgrest import configured as postgrest_configured  # noqa: E402
from eval_video_resolution import ResolutionError, build_basename_index, resolve_filename  # noqa: E402
import r2_videos  # noqa: E402


def _get_db():
    """Direct Postgres (``db.py``) when reachable, else the PostgREST adapter.

    This sandbox's network blocks direct Postgres (port 5432/6543) but allows
    HTTPS - ``db.get_db()`` swallows connection failures and returns ``None``,
    so a real but unreachable DSN falls through to PostgREST rather than
    silently doing nothing. Both backends implement the same method surface
    (see ``db_postgrest.py``'s module docstring), so nothing downstream needs
    to know which one is in use.
    """
    db = db_module.get_db()
    if db is not None:
        return db
    if postgrest_configured():
        return PostgrestIncidentDB()
    return None

EVAL_DATA_DIR = Path(__file__).resolve().parents[1] / "eval_data"
WORKBOOK_PATH = EVAL_DATA_DIR / "ground_truth_labelling.xlsx"

_EXCEL_EPOCH = datetime(1899, 12, 30)  # Excel's day-0, accounting for its leap-year bug

_LABEL_FIXES = {"animal": "Animal Attack"}


def _excel_serial_to_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return _EXCEL_EPOCH + timedelta(days=float(value))


def _sheet_rows(workbook, sheet_name: str) -> list[dict]:
    ws = workbook[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for raw in rows[1:]:
        row = dict(zip(header, raw))
        if any(v not in (None, "") for v in row.values()):
            out.append(row)
    return out


def _fix_type_label(type_value: str | None) -> str | None:
    if type_value is None:
        return None
    return _LABEL_FIXES.get(type_value.strip().lower(), type_value)


def load_gt_incidents(workbook) -> list[dict]:
    """The 80 real rows - filters out the ~934 empty formatting-artifact rows."""
    rows = _sheet_rows(workbook, "gt_incidents")
    return [r for r in rows if (r.get("Type") or "").strip()]


def ingest(*, dry_run: bool = False) -> dict:
    """Import the workbook into the live DB. Returns a small summary dict."""
    workbook = openpyxl.load_workbook(WORKBOOK_PATH, data_only=True)

    incidents = load_gt_incidents(workbook)
    entities = _sheet_rows(workbook, "gt_entities")
    instruments = _sheet_rows(workbook, "gt_instruments")
    assets = _sheet_rows(workbook, "gt_assets")

    entities_by_incident: dict[str, list[dict]] = {}
    for row in entities:
        entities_by_incident.setdefault(row["Incident_ID (P_key, F_key)"], []).append(row)
    instruments_by_incident: dict[str, list[dict]] = {}
    for row in instruments:
        instruments_by_incident.setdefault(row["Incident_ID (P_key, F_key)"], []).append(row)
    assets_by_incident: dict[str, list[dict]] = {}
    for row in assets:
        assets_by_incident.setdefault(row["Incident_ID (P_key, F_key)"], []).append(row)

    basename_index = build_basename_index(r2_videos.list_video_keys())

    db = _get_db()
    if db is None and not dry_run:
        raise RuntimeError(
            "Neither direct Postgres (INCIDENT_DB_DSN) nor PostgREST "
            "(INCIDENT_SUPABASE_URL/INCIDENT_SUPABASE_SERVICE_ROLE_KEY) is reachable - "
            "cannot ingest (pass dry_run=True to only validate)"
        )

    summary = {"incidents": 0, "entities": 0, "instruments": 0, "assets": 0, "unresolved_videos": []}

    for row in incidents:
        filename = row["Filename"].strip()
        incident_id = row["Incident_ID (P_key)"].strip()
        try:
            r2_key = resolve_filename(filename, basename_index)
        except ResolutionError as exc:
            summary["unresolved_videos"].append((filename, str(exc)))
            r2_key = None

        gt_fields = {
            "type": _fix_type_label(row.get("Type")),
            "start_timestamp": row.get("Start_Timestamp"),
            "end_timestamp": row.get("End_Timestamp"),
            "duration": row.get("Duration"),
            "description": row.get("Description"),
            "severity_level": row.get("Severity_Level"),
            "labelled_by": row.get("Labelled_By"),
            "labelled_datetime": _excel_serial_to_datetime(row.get("Labelled_DateTime")),
        }

        if dry_run:
            summary["incidents"] += 1
            summary["entities"] += len(entities_by_incident.get(incident_id, []))
            summary["instruments"] += len(instruments_by_incident.get(incident_id, []))
            summary["assets"] += len(assets_by_incident.get(incident_id, []))
            continue

        db.upsert_video(incident_id, filepath=r2_key or filename)
        db.insert_gt_incident(incident_id, fields=gt_fields)

        for e in entities_by_incident.get(incident_id, []):
            db.add_gt_entity(
                incident_id,
                entity_id=e["Entity_ID (P_key)"],
                type=e.get("Type"),
                description=e.get("Description"),
                image=e.get("Image") or None,
            )
            summary["entities"] += 1

        for i in instruments_by_incident.get(incident_id, []):
            db.add_gt_instrument(
                incident_id,
                instrument_id=i["Instrument_ID (P_key)"],
                entity_id=i.get("Entity_ID") or None,
                name=i.get("Name"),
                description=i.get("Description"),
                threat_level=i.get("Threat_Level"),
                image=i.get("Image") or None,
            )
            summary["instruments"] += 1

        for a in assets_by_incident.get(incident_id, []):
            db.add_gt_asset(
                incident_id,
                asset_id=a["Asset_ID (P_key)"],
                name=a.get("Name"),
                description=a.get("Description"),
                image=a.get("Image") or None,
            )
            summary["assets"] += 1

        summary["incidents"] += 1

    return summary


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    result = ingest(dry_run=dry_run)
    print(f"{'[dry run] ' if dry_run else ''}ingested: {result['incidents']} incidents, "
          f"{result['entities']} entities, {result['instruments']} instruments, {result['assets']} assets")
    if result["unresolved_videos"]:
        print(f"WARNING: {len(result['unresolved_videos'])} filenames did not resolve to an R2 object:")
        for filename, error in result["unresolved_videos"]:
            print(f"  {filename}: {error}")
