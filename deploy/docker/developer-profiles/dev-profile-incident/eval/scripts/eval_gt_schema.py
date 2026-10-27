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
from incident_report import canonical_incident_type


def _int_or_none(value):
    return int(value) if isinstance(value, (int, float)) else None


_TRUE = {"true", "yes", "y", "1", "x"}


def out_of_taxonomy_fields(row: dict) -> dict:
    """``{"out_of_taxonomy", "nearest_type"}`` from a ground-truth incident row.

    Confirmed out-of-taxonomy status comes only from the ground truth's own optional columns
    ``Out_Of_Taxonomy`` and ``Nearest_Type`` (carried by the frozen ground truth, PR 5), never
    from a prediction and never from the review workbook's ``OUT_OF_TAXONOMY_CANDIDATE`` flag.
    A workbook without the columns has no out-of-taxonomy clips.
    """
    flag = row.get("Out_Of_Taxonomy")
    confirmed = flag is True or str(flag or "").strip().lower() in _TRUE
    nearest = canonical_incident_type(_fix_type_label(row.get("Nearest_Type"))) if row.get("Nearest_Type") else None
    return {"out_of_taxonomy": confirmed, "nearest_type": nearest if confirmed else None}


def load_gt_index(workbook_path: Path = WORKBOOK_PATH) -> dict:
    """Everything the split generator and batch runner need, built once.

    Returns::

        {
          "by_category": {"<category>": [{"filename": ..., "incident_id": ...}, ...], ...},
          "by_incident_id": {"<incident_id>": {"filename": ..., "category": ..., "p1_shaped": {...}}, ...},
        }
    """
    workbook = openpyxl.load_workbook(workbook_path, data_only=True)
    return gt_index_from_rows(load_gt_incidents(workbook), _sheet_rows(workbook, "gt_entities"),
                              _sheet_rows(workbook, "gt_instruments"), _sheet_rows(workbook, "gt_assets"))


def load_frozen_gt_index(directory: Path, *, allow_candidate: bool = False) -> dict:
    """``load_gt_index``'s shape from a frozen ground-truth directory (PR 5), checksums verified.

    Refuses a directory that is not ``frozen`` (a candidate awaiting approval) unless
    ``allow_candidate`` is set, which is for plumbing tests only, never for reported results.
    The result also carries ``version``, ``status``, ``split`` and ``manifest``.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import ground_truth_freeze

    data = ground_truth_freeze.read_frozen(Path(directory), allow_candidate=allow_candidate)
    sheets = data["sheets"]
    index = gt_index_from_rows(sheets["gt_incidents"], sheets["gt_entities"], sheets["gt_instruments"],
                               sheets["gt_assets"])
    return {**index, "version": data["version"], "status": data["status"], "split": data["split"],
            "manifest": data["manifest"]}


def gt_index_from_rows(incidents: list[dict], entities: list[dict], instruments: list[dict], assets: list[dict]) -> dict:
    """The index from workbook-shaped rows (the workbook itself, or a frozen ground truth)."""
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
                "type": canonical_incident_type(category),
                "start_timestamp": _int_or_none(row.get("Start_Timestamp")),
                "end_timestamp": _int_or_none(row.get("End_Timestamp")),
                "duration": _int_or_none(row.get("Duration")),
                "description": row.get("Description"),
                "severity_level": _int_or_none(row.get("Severity_Level")),
                "confidence_score": None,
                **out_of_taxonomy_fields(row),
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
