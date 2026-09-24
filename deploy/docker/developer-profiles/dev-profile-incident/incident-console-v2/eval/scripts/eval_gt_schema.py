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

"""Read the GT workbook directly into P1's own output schema shape.

One shared source of truth for the workbook's 80 real, video-backed GT rows
(reuses ``eval_ingest_gt.load_gt_incidents``'s same filter/label-fix rules),
consumed by both the split-manifest generator (needs filename+category per
incident) and the batch runner (needs each incident's GT reshaped exactly
like P1's own JSON output, for text-exemplar construction and for the
"ground_truth" field persisted in every result).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl

from eval_ingest_gt import WORKBOOK_PATH, _fix_type_label, _sheet_rows, load_gt_incidents


def _int_or_none(value):
    return int(value) if isinstance(value, (int, float)) else None


def load_gt_index(workbook_path: Path = WORKBOOK_PATH) -> dict:
    """Everything the split generator and batch runner need, built once.

    Returns::

        {
          "by_category": {"<category>": [{"filename": ..., "incident_id": ...}, ...], ...},
          "by_incident_id": {"<incident_id>": {"filename": ..., "category": ..., "p1_shaped": {...}}, ...},
        }
    """
    workbook = openpyxl.load_workbook(workbook_path, data_only=True)
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

    by_category: dict[str, list[dict]] = {}
    by_incident_id: dict[str, dict] = {}

    for row in incidents:
        filename = row["Filename"].strip()
        incident_id = row["Incident_ID (P_key)"].strip()
        category = _fix_type_label(row.get("Type"))

        p1_shaped = {
            "incident": {
                "type": category.lower() if category else None,
                "start_timestamp": _int_or_none(row.get("Start_Timestamp")),
                "end_timestamp": _int_or_none(row.get("End_Timestamp")),
                "duration": _int_or_none(row.get("Duration")),
                "description": row.get("Description"),
                "severity_level": _int_or_none(row.get("Severity_Level")),
                "confidence_score": None,
            },
            "entities": [
                {
                    "entity_id": e["Entity_ID (P_key)"],
                    "type": e.get("Type"),
                    "description": e.get("Description"),
                }
                for e in entities_by_incident.get(incident_id, [])
            ],
            "instruments": [
                {
                    "instrument_id": i["Instrument_ID (P_key)"],
                    "entity_id": i.get("Entity_ID") or None,
                    "name": i.get("Name"),
                    "description": i.get("Description"),
                    "threat_level": _int_or_none(i.get("Threat_Level")),
                }
                for i in instruments_by_incident.get(incident_id, [])
            ],
            "assets": [
                {
                    "asset_id": a["Asset_ID (P_key)"],
                    "name": a.get("Name"),
                    "description": a.get("Description"),
                }
                for a in assets_by_incident.get(incident_id, [])
            ],
        }

        by_category.setdefault(category, []).append({"filename": filename, "incident_id": incident_id})
        by_incident_id[incident_id] = {"filename": filename, "category": category, "p1_shaped": p1_shaped}

    return {"by_category": by_category, "by_incident_id": by_incident_id}


if __name__ == "__main__":
    index = load_gt_index()
    for category, rows in index["by_category"].items():
        print(f"{category}: {len(rows)} videos")
    sample_id = next(iter(index["by_incident_id"]))
    import json

    print(f"\nsample ({sample_id}):")
    print(json.dumps(index["by_incident_id"][sample_id]["p1_shaped"], indent=2))
