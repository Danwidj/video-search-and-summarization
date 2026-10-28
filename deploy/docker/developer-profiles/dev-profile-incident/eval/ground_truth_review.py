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

"""Ground-truth audit and proposed corrections (PR 3), against annotation-guidelines-v1.0.

``audit`` reads the four data sheets of the human-labelled workbook (values only) and
returns one ``Change`` per finding, in a deterministic order. Each finding has a class:

- ``verified_correction``: provable from the workbook itself or the tracked dataset
  manifest, with no video needed (a malformed id, a ``_demo`` filename, an exact duplicate
  row, cells outside the documented columns);
- ``rule_based_proposal``: follows from an approved guideline rule applied to what the
  annotator recorded (a vehicle recorded as an instrument is an asset, A1);
- ``needs_video_review``: the guideline asks for a check that only the video can answer;
  **no value is proposed**;
- ``informational``: recorded, no change proposed (renumbering is never proposed).

No rule infers a visual fact from a filename or a description. Description wording is used
only to *select* records for video review, never to propose a value.

``apply_changes`` writes the proposals into a working copy of the workbook (opened with its
formulas), adds review columns, highlights changed cells and appends - never deletes - records.
Nothing here is final ground truth: PR 4 reviews, PR 5 freezes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

from dataset_manifest import canonical_basename

GUIDELINE_VERSION = "annotation-guidelines-v1.0"
REVIEW_STATUSES = ("Pending", "Approved", "Rejected")
CHANGE_TYPES = ("verified_correction", "rule_based_proposal", "needs_video_review", "informational")

SHEETS = {
    "gt_incidents": {"id": "Incident_ID (P_key)", "incident": "Incident_ID (P_key)",
                     "columns": ["Filename", "Incident_ID (P_key)", "Type", "Start_Timestamp", "End_Timestamp", "Duration",
                                 "Description", "Severity_Level", "Labelled_By", "Labelled_DateTime"]},
    "gt_entities": {"id": "Entity_ID (P_key)", "incident": "Incident_ID (P_key, F_key)",
                    "columns": ["Filename", "Incident_ID (P_key, F_key)", "Entity_ID (P_key)", "Type", "Description", "Image"]},
    "gt_instruments": {"id": "Instrument_ID (P_key)", "incident": "Incident_ID (P_key, F_key)",
                       "columns": ["Filename", "Incident_ID (P_key, F_key)", "Instrument_ID (P_key)", "Entity_ID", "Name",
                                   "Description", "Threat_Level", "Image"]},
    "gt_assets": {"id": "Asset_ID (P_key)", "incident": "Incident_ID (P_key, F_key)",
                  "columns": ["Filename", "Incident_ID (P_key, F_key)", "Asset_ID (P_key)", "Name", "Description", "Image"]},
}
ID_PREFIX = {"gt_entities": "E", "gt_instruments": "I", "gt_assets": "A"}
FIVE_TYPES = {"road accident", "burglary", "explosion", "assault", "animal attack"}
LEGACY_TYPE_LABELS = {"animal": "Animal Attack", "fighting": "Assault"}

RULES = {
    # Filename is a protected field (user decision 2026-10-28): never modified. A `_demo` name is resolved to its
    # clip by dataset_manifest.canonical_basename wherever it is read, so R01 only records the alias.
    "R01": ("informational", "Filename names the presentation-demo copy; it is kept as annotated and resolved to its clip",
            "§9; dataset-manifest-v1 (canonical filename)"),
    "R02": ("verified_correction", "Exact duplicate of an earlier row of the same incident (after R01)", "§9 (one row per record)"),
    "R03": ("verified_correction", "Identifier has leading or trailing whitespace", "§9 (ids are trimmed text)"),
    "R05": ("verified_correction", "Value in a column outside the documented schema (not ground truth)", "§9 field map"),
    "R10": ("rule_based_proposal", "A vehicle is not hand-held, so it is never an instrument; it is an asset", "A1, §4, §6"),
    "R20": ("needs_video_review", "Explosive device: rate threat by plausible capability and observed context", "A3, §4.1 rule 4"),
    "R21": ("needs_video_review", "Generic or vague object name: use the most general true noun, or 'unidentified object'", "A5"),
    "R22": ("needs_video_review", "Possible clip outside the five types; review flag only, the type is not changed", "A8, §2.1.2"),
    "R23": ("needs_video_review", "Severity-1 animal incident: re-check severity with the demonstrated-danger rule", "A9, §2.3"),
    "R24": ("needs_video_review", "Responders' equipment: instrument only if held and used; threat rated separately", "A12, §4.1 rule 3"),
    "R25": ("needs_video_review", "Age or gender words: keep only if supported by visual cues", "A7, §7"),
    "R26": ("needs_video_review", "Incident window does not fit the video's length", "§2.2"),
    "R27": ("needs_video_review", "Start is not before end, or a timestamp is negative", "§2.2"),
    "R28": ("verified_correction", "Duration is not End - Start", "§2.2 (duration is derived)"),
    "R29": ("needs_video_review", "Instrument holder is not an entity of the same incident", "§4 (holder)"),
    "R30": ("informational", "Item ids are not sequential; renumbering is not proposed", "§3, §5 (ids)"),
    "R31": ("needs_video_review", "Severity or threat outside 1-5, or not a whole number", "§2.3, §4.1"),
    "R32": ("needs_video_review", "Required text is empty", "§7"),
    "R33": ("needs_video_review", "Type is not one of the five categories", "§2.1"),
    "R34": ("needs_video_review", "Wording states an unobservable conclusion (identity, intent, outcome)", "§7 wording rules, principle 1"),
}

# Candidates named in the approved guideline's decision record (A8, A9).
OUT_OF_TAXONOMY_CANDIDATES = ("Explosion011", "Explosion014")
A9_PRIORITY = ("Animal004", "Animal011", "Animal012")

VEHICLE_NAMES = {"car", "suv", "truck", "van", "bus", "motorcycle", "motorbike", "bicycle", "bike", "scooter", "vehicle",
                 "lorry", "pickup", "pickup truck", "taxi"}
EXPLOSIVE = re.compile(r"explos|bomb|grenade|dynamite|detonat|incendiar|molotov", re.IGNORECASE)
VAGUE_NAMES = {"object", "item", "thing", "things", "weapon", "tool", "hand tool", "device", "stuff", "unknown", "something"}
RESPONDER_EQUIPMENT = re.compile(r"extinguisher|\bhose\b", re.IGNORECASE)
DEMOGRAPHIC = re.compile(r"\b(man|men|woman|women|boy|boys|girl|girls|child|children|kid|kids|baby|toddler|teen\w*|"
                         r"elderly|old|young|male|female|lady|ladies|gentleman)\b", re.IGNORECASE)
CONCLUSION = re.compile(r"\b(owner|owners|intend\w*|wants? to|kill\w*|dead|died|dies|unconscious|fatal\w*|drunk|"
                        r"angry|furious|scared|afraid|thief|thieves|criminal|robber|burglar)\b", re.IGNORECASE)


@dataclass
class Change:
    rule: str
    sheet: str
    row: int                      # Excel row in the source sheet (new records: the row they are appended at)
    incident_id: str
    record_id: str
    field: str
    original_value: object
    proposed_value: object        # None for needs_video_review / informational: no value is proposed
    reason: str
    evidence: str
    confidence: str
    change_type: str = ""
    guideline_ref: str = ""
    review_flag: str = ""
    change_id: str = ""
    review_status: str = "Pending"
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.change_type, _, self.guideline_ref = RULES[self.rule]
        if self.change_type in ("needs_video_review", "informational"):
            self.proposed_value = None


def _clean(value):
    return value.strip() if isinstance(value, str) else value


def read_data_rows(workbook_values) -> dict[str, list[tuple[int, dict]]]:
    """``{sheet: [(excel_row, {header: value})]}`` for non-empty rows (gt_incidents: rows with a Type)."""
    rows: dict[str, list[tuple[int, dict]]] = {}
    for sheet in SHEETS:
        ws = workbook_values[sheet]
        header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
        out = []
        for excel_row, raw in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            record = dict(zip(header, raw))
            if sheet == "gt_incidents":
                if not str(record.get("Type") or "").strip():
                    continue
            elif not any(v not in (None, "") for k, v in record.items() if k):
                continue
            out.append((excel_row, record))
        rows[sheet] = out
    return rows


def stray_cells(workbook_values, sheet: str, data_rows: list[int]) -> list[tuple[int, int, object]]:
    """``(row, column, value)`` of non-empty cells right of the documented columns, on data rows."""
    ws = workbook_values[sheet]
    documented = len(SHEETS[sheet]["columns"])
    found = []
    for excel_row in data_rows:
        for cell in ws[excel_row]:
            if cell.column > documented and cell.value not in (None, ""):
                found.append((excel_row, cell.column, cell.value))
    return found


def _num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _video_evidence(clips: dict[str, dict], filename: str, start=None, end=None) -> str:
    clip = clips.get(canonical_basename(filename or ""))
    where = f"local copy {clip['local_path']}" if clip else "clip not in dataset-manifest-v1"
    window = ""
    if _num(start) is not None and _num(end) is not None:
        window = f", incident window {_num(start):g}-{_num(end):g} s"
    return f"Required: watch {canonical_basename(filename or '?')} ({where}{window})"


def audit(workbook_values, manifest: dict) -> tuple[list[Change], dict]:
    """All findings, in a deterministic order, plus facts for the report."""
    rows = read_data_rows(workbook_values)
    clips = {c["filename"]: c for c in manifest["clips"]}
    incidents = {}
    for excel_row, record in rows["gt_incidents"]:
        incidents.setdefault(_clean(record["Incident_ID (P_key)"]), (excel_row, record))
    changes: list[Change] = []

    def add(rule, sheet, row, incident_id, record_id, fld, original, proposed, reason_detail, evidence, confidence,
            flag="", **extra):
        _, reason, _ = RULES[rule]
        changes.append(Change(rule, sheet, row, incident_id, record_id, fld, original, proposed,
                              f"{reason}. {reason_detail}".strip(". ").strip() + ".", evidence, confidence,
                              review_flag=flag, extra=extra))

    window_of = {i: (r.get("Start_Timestamp"), r.get("End_Timestamp"), r.get("Filename")) for i, (_, r) in incidents.items()}

    def evidence_for(incident_id):
        start, end, filename = window_of.get(incident_id, (None, None, f"{incident_id}_x264.mp4"))
        return _video_evidence(clips, filename or f"{incident_id}_x264.mp4", start, end)

    # --- verified: filenames, ids, duplicates, labels, stray cells, durations ---------------
    seen_rows: dict[str, tuple[int, tuple]] = {}
    for sheet, spec in SHEETS.items():
        for excel_row, record in rows[sheet]:
            incident_id = _clean(record.get(spec["incident"]))
            record_id = _clean(record.get(spec["id"]))
            filename = record.get("Filename")
            if isinstance(filename, str) and canonical_basename(filename.strip()) != filename.strip():
                canonical = canonical_basename(filename.strip())
                if canonical in clips:
                    add("R01", sheet, excel_row, incident_id, record_id, "Filename", filename, canonical,
                        f"dataset-manifest-v1 lists R2 key {clips[canonical]['r2_key']} under the ground-truth filename "
                        f"{canonical}", "Not required: dataset-manifest-v1", "High (verified)")
            for column in (spec["incident"], spec["id"]) + (("Entity_ID",) if sheet == "gt_instruments" else ()):
                value = record.get(column)
                if isinstance(value, str) and value != value.strip():
                    add("R03", sheet, excel_row, incident_id, record_id, column, value, value.strip(),
                        "Stripping it leaves the same identifier", "Not required: workbook value", "High (verified)")
            if sheet == "gt_incidents":
                key = tuple(_clean(record.get(c)) if c != "Filename" else canonical_basename(str(record.get(c) or "").strip())
                            for c in spec["columns"])
                if incident_id in seen_rows:
                    first_row, first_key = seen_rows[incident_id]
                    if key == first_key:
                        add("R02", sheet, excel_row, incident_id, record_id, "(row)", "present",
                            f"remove (duplicate of row {first_row})",
                            f"Every field equals row {first_row} once the filename is canonical",
                            "Not required: workbook values", "High (verified)", flag="PROPOSED_REMOVAL_DUPLICATE")
                    else:
                        add("R32", sheet, excel_row, incident_id, record_id, "(row)", "present", None,
                            f"Second row for {incident_id} differs from row {first_row}; which is correct needs review",
                            evidence_for(incident_id), "Unknown - needs video", flag="CONFLICTING_DUPLICATE")
                else:
                    seen_rows[incident_id] = (excel_row, key)
                label = str(record.get("Type") or "").strip()
                if label.lower() not in FIVE_TYPES and label.lower() not in LEGACY_TYPE_LABELS:
                    add("R33", sheet, excel_row, incident_id, record_id, "Type", record.get("Type"), None,
                        "", evidence_for(incident_id), "Unknown - needs video")
                start, end, duration = (_num(record.get(c)) for c in ("Start_Timestamp", "End_Timestamp", "Duration"))
                if start is not None and end is not None:
                    if start < 0 or end <= start:
                        add("R27", sheet, excel_row, incident_id, record_id, "Start_Timestamp/End_Timestamp",
                            f"{start:g}-{end:g}", None, "", evidence_for(incident_id), "Unknown - needs video")
                    elif duration is not None and abs(duration - (end - start)) > 1e-9:
                        add("R28", sheet, excel_row, incident_id, record_id, "Duration", record.get("Duration"),
                            "=End_Timestamp-Start_Timestamp", f"End - Start is {end - start:g}",
                            "Not required: workbook values", "High (verified)")
                    clip = clips.get(canonical_basename(str(record.get("Filename") or "").strip()))
                    if clip and clip.get("duration_seconds") is not None and end >= clip["duration_seconds"] + 1:
                        add("R26", sheet, excel_row, incident_id, record_id, "End_Timestamp", record.get("End_Timestamp"),
                            None, f"The video is {clip['duration_seconds']:g} s long (MP4 header, dataset-manifest-v1); "
                            f"the latest possible end is {int(clip['duration_seconds'])} s",
                            evidence_for(incident_id), "Unknown - needs video")
                severity = _num(record.get("Severity_Level"))
                if severity is None or severity not in (1, 2, 3, 4, 5):
                    add("R31", sheet, excel_row, incident_id, record_id, "Severity_Level", record.get("Severity_Level"),
                        None, "", evidence_for(incident_id), "Unknown - needs video")
                if not str(record.get("Description") or "").strip():
                    add("R32", sheet, excel_row, incident_id, record_id, "Description", record.get("Description"), None,
                        "", evidence_for(incident_id), "Unknown - needs video")

        for excel_row, column, value in stray_cells(workbook_values, sheet, [r for r, _ in rows[sheet]]):
            record = dict(rows[sheet])[excel_row]
            add("R05", sheet, excel_row, _clean(record.get(spec["incident"])), _clean(record.get(spec["id"])),
                f"column {column} (undocumented)", value, "",
                "Left over from the hidden Metadata sheet's id lists; ingestion ignores it",
                "Not required: workbook layout", "High (verified)")

    # --- item rules ----------------------------------------------------------------------
    entities_by_incident: dict[str, set] = {}
    for _, record in rows["gt_entities"]:
        entities_by_incident.setdefault(_clean(record["Incident_ID (P_key, F_key)"]), set()).add(
            _clean(record["Entity_ID (P_key)"]))
    next_asset_number: dict[str, int] = {}
    for _, record in rows["gt_assets"]:
        incident_id = _clean(record["Incident_ID (P_key, F_key)"])
        match = re.match(r"A(\d+)$", str(_clean(record["Asset_ID (P_key)"])))
        if match:
            next_asset_number[incident_id] = max(next_asset_number.get(incident_id, 0), int(match.group(1)))

    for excel_row, record in rows["gt_instruments"]:
        incident_id = _clean(record["Incident_ID (P_key, F_key)"])
        instrument_id = _clean(record["Instrument_ID (P_key)"])
        name = str(record.get("Name") or "").strip()
        holder = _clean(record.get("Entity_ID"))
        if name.lower() in VEHICLE_NAMES:
            new_id = f"A{next_asset_number.get(incident_id, 0) + 1}"
            next_asset_number[incident_id] = next_asset_number.get(incident_id, 0) + 1
            add("R10", "gt_instruments", excel_row, incident_id, instrument_id, "(row)", "present",
                f"remove: reclassified as asset {new_id}",
                f"The annotator recorded '{name}'; the threat level does not carry over (assets have none)",
                "Not required for the classification; video check of relevance recommended", "High",
                flag="PROPOSED_REMOVAL_RECLASSIFIED")
            add("R10", "gt_assets", 0, incident_id, new_id, "(new row)", None,
                {"Filename": record.get("Filename"), "Incident_ID (P_key, F_key)": incident_id, "Asset_ID (P_key)": new_id,
                 "Name": record.get("Name"), "Description": record.get("Description"), "Image": record.get("Image")},
                f"New asset for instrument {instrument_id}; next free asset id of {incident_id}",
                "Not required for the classification; video check of relevance recommended", "High", flag="NEW_RECORD")
        if EXPLOSIVE.search(name):
            add("R20", "gt_instruments", excel_row, incident_id, instrument_id, "Threat_Level", record.get("Threat_Level"),
                None, "", evidence_for(incident_id), "Unknown - needs video")
        if name.lower() in VAGUE_NAMES or re.search(r"\bitem\b", name, re.IGNORECASE):
            add("R21", "gt_instruments", excel_row, incident_id, instrument_id, "Name", record.get("Name"), None, "",
                evidence_for(incident_id), "Unknown - needs video")
        if RESPONDER_EQUIPMENT.search(name):
            add("R24", "gt_instruments", excel_row, incident_id, instrument_id, "(classification)", record.get("Name"),
                None, "", evidence_for(incident_id), "Unknown - needs video")
        if holder and holder not in entities_by_incident.get(incident_id, set()):
            add("R29", "gt_instruments", excel_row, incident_id, instrument_id, "Entity_ID", record.get("Entity_ID"), None,
                f"No entity {holder} in {incident_id}", evidence_for(incident_id), "Unknown - needs video")
        threat = _num(record.get("Threat_Level"))
        if threat is None or threat not in (1, 2, 3, 4, 5):
            add("R31", "gt_instruments", excel_row, incident_id, instrument_id, "Threat_Level", record.get("Threat_Level"),
                None, "", evidence_for(incident_id), "Unknown - needs video")

    for excel_row, record in rows["gt_assets"]:
        name = str(record.get("Name") or "").strip()
        if name.lower() in VAGUE_NAMES or re.search(r"\bitem\b", name, re.IGNORECASE):
            incident_id = _clean(record["Incident_ID (P_key, F_key)"])
            add("R21", "gt_assets", excel_row, incident_id, _clean(record["Asset_ID (P_key)"]), "Name", record.get("Name"),
                None, "", evidence_for(incident_id), "Unknown - needs video")

    for sheet in ("gt_entities", "gt_instruments", "gt_assets"):
        spec = SHEETS[sheet]
        by_incident: dict[str, list[tuple[int, str]]] = {}
        for excel_row, record in rows[sheet]:
            by_incident.setdefault(_clean(record[spec["incident"]]), []).append((excel_row, str(_clean(record[spec["id"]]))))
            if sheet != "gt_instruments" and not str(record.get("Description") or "").strip():
                add("R32", sheet, excel_row, _clean(record[spec["incident"]]), _clean(record[spec["id"]]), "Description",
                    record.get("Description"), None, "", evidence_for(_clean(record[spec["incident"]])), "Unknown - needs video")
        for incident_id, items in sorted(by_incident.items()):
            numbers = sorted(int(m.group(1)) for _, i in items if (m := re.match(rf"{ID_PREFIX[sheet]}(\d+)$", i)))
            if numbers and numbers != list(range(1, len(numbers) + 1)):
                add("R30", sheet, items[0][0], incident_id, ",".join(i for _, i in items), "(ids)",
                    ",".join(i for _, i in items), None, f"Expected {ID_PREFIX[sheet]}1..{ID_PREFIX[sheet]}{len(numbers)}",
                    "Not required", "n/a")

    # --- incident-level review rules -------------------------------------------------------
    for incident_id, (excel_row, record) in sorted(incidents.items()):
        label = str(record.get("Type") or "").strip().lower()
        if incident_id in OUT_OF_TAXONOMY_CANDIDATES:
            add("R22", "gt_incidents", excel_row, incident_id, incident_id, "(review flag)", record.get("Type"), None,
                "Named in the guideline's A8 decision record; the type stays one of the five",
                evidence_for(incident_id), "Unknown - needs video", flag="OUT_OF_TAXONOMY_CANDIDATE")
        if label in ("animal", "animal attack") and _num(record.get("Severity_Level")) == 1:
            priority = "priority (named in A9)" if incident_id in A9_PRIORITY else ""
            add("R23", "gt_incidents", excel_row, incident_id, incident_id, "Severity_Level", record.get("Severity_Level"),
                None, priority, evidence_for(incident_id), "Unknown - needs video")
        description = str(record.get("Description") or "")
        if DEMOGRAPHIC.search(description):
            add("R25", "gt_incidents", excel_row, incident_id, incident_id, "Description", description, None,
                f"Words: {', '.join(sorted({m.group(0).lower() for m in DEMOGRAPHIC.finditer(description)}))}",
                evidence_for(incident_id), "Unknown - needs video")
        if CONCLUSION.search(description):
            add("R34", "gt_incidents", excel_row, incident_id, incident_id, "Description", description, None,
                f"Words: {', '.join(sorted({m.group(0).lower() for m in CONCLUSION.finditer(description)}))}",
                evidence_for(incident_id), "Unknown - needs video")
    for excel_row, record in rows["gt_entities"]:
        description = str(record.get("Description") or "")
        incident_id = _clean(record["Incident_ID (P_key, F_key)"])
        entity_id = _clean(record["Entity_ID (P_key)"])
        for rule, pattern in (("R25", DEMOGRAPHIC), ("R34", CONCLUSION)):
            if pattern.search(description):
                add(rule, "gt_entities", excel_row, incident_id, entity_id, "Description", description, None,
                    f"Words: {', '.join(sorted({m.group(0).lower() for m in pattern.finditer(description)}))}",
                    evidence_for(incident_id), "Unknown - needs video")

    # A row proposed for removal as an exact duplicate gets no further field edits.
    removed = {(c.sheet, c.row) for c in changes if c.rule == "R02"}
    changes = [c for c in changes if c.rule == "R02" or (c.sheet, c.row) not in removed]

    order = {sheet: i for i, sheet in enumerate(SHEETS)}
    changes.sort(key=lambda c: (c.incident_id or "", order[c.sheet], c.row or 10**6, c.rule, c.field, str(c.record_id)))
    for number, change in enumerate(changes, start=1):
        change.change_id = f"CL-{number:04d}"
    facts = {
        "incidents": len(incidents),
        "rows": {sheet: len(rows[sheet]) for sheet in SHEETS},
        "incident_rows": len(rows["gt_incidents"]),
        "dataset_clips": len(clips),
        "incidents_without_clip": sorted(i for i, (_, r) in incidents.items()
                                         if canonical_basename(str(r.get("Filename") or "").strip()) not in clips),
        "clips_without_incident": sorted(c["incident_id"] for c in manifest["clips"] if c["incident_id"] not in incidents),
        "type_labels": dict(sorted(Counter(str(r.get("Type")).strip() for _, r in rows["gt_incidents"]).items())),
        "type_dropdown": _type_dropdown(workbook_values),
    }
    return changes, facts


def _type_dropdown(workbook_values) -> str | None:
    for validation in workbook_values["gt_incidents"].data_validations.dataValidation:
        if "C" in str(validation.sqref) and validation.type == "list":
            return validation.formula1
    return None


def change_log_digest(changes: list[Change]) -> str:
    """SHA-256 of the change log content (independent of the xlsx container, which embeds timestamps)."""
    rows = [{k: v for k, v in asdict(c).items() if k != "extra"} for c in changes]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
