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

"""Prepare, validate and (only with explicit approval) freeze a ground-truth version (PR 5).

Pure functions; ``scripts/gt_freeze.py`` does the I/O.

- ``schema_problems`` checks the corrected records against the guidelines' domains and the
  dataset manifest (types, levels, ids, holders, timestamps within the clip).
- ``split_v2`` turns the existing seeded split manifests into ``split-v2`` (dev = the 25 former
  few-shot clips, test = the 55 evaluation clips; membership unchanged) and ``split_problems``
  checks it against the ground truth.
- ``blocking_issues`` lists everything that stops a freeze: entries still ``Pending``, linked
  entries decided apart, unusable AI proposals, schema or split problems. **A Pending entry is
  never treated as Approved**; it blocks.
- ``freeze_status`` is ``frozen`` only when nothing blocks **and** an approval record names
  exactly this candidate (its workbook and records digests) and its exclusions. Otherwise the
  output is a ``candidate`` and says why.
- ``read_frozen`` verifies every file against ``MANIFEST.json`` and refuses a candidate unless
  the caller explicitly allows one.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import ground_truth_correction as gtc
import ground_truth_review as gtr
from dataset_manifest import canonical_basename

VERSION = "ground-truth-v1.0"
SPLIT_VERSION = "split-v2"
FILES = ("ground_truth.json", "split-v2.json")
ID_PATTERNS = {"gt_entities": r"E\d+", "gt_instruments": r"I\d+", "gt_assets": r"A\d+"}
ENTITY_TYPES = {"human", "animal"}
# The frozen records' columns per sheet: the workbook's documented columns, plus the
# optional out-of-taxonomy columns (methodology v1.0, Option C) on incidents.
COLUMNS = {sheet: spec["columns"] + (list(gtc.NOTE_FIELDS) if sheet == "gt_incidents" else [])
           for sheet, spec in gtr.SHEETS.items()}
TIME_TOLERANCE_SECONDS = 1.0  # integer-second labels against a fractional clip length


class FrozenGroundTruthError(RuntimeError):
    """A frozen ground-truth directory is missing, altered, or not approved for use."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True, default=str, ensure_ascii=False) + "\n").encode()


# --- validation -----------------------------------------------------------------------------

def schema_problems(records: dict[str, list[dict]], manifest: dict) -> list[str]:
    problems = []
    clips = {c["filename"]: c for c in manifest["clips"]}
    incidents = {}
    for record in records["gt_incidents"]:
        incident_id = gtr._clean(record.get("Incident_ID (P_key)"))
        where = f"gt_incidents {incident_id}"
        if incident_id in incidents:
            problems.append(f"{where}: duplicate incident")
        incidents[incident_id] = record
        # Filename is kept as annotated (protected); a presentation-demo name resolves to its clip.
        filename = str(record.get("Filename") or "").strip()
        clip = clips.get(canonical_basename(filename))
        if clip is None:
            problems.append(f"{where}: filename {filename!r} is not a dataset-manifest-v1 clip")
        elif clip["incident_id"] != incident_id:
            problems.append(f"{where}: filename belongs to {clip['incident_id']}")
        label = str(record.get("Type") or "").strip().lower()
        if gtr.LEGACY_TYPE_LABELS.get(label, label).lower() not in gtr.FIVE_TYPES:
            problems.append(f"{where}: type {record.get('Type')!r} is not one of the five")
        severity = gtr._num(record.get("Severity_Level"))
        if severity not in (1, 2, 3, 4, 5):
            problems.append(f"{where}: severity {record.get('Severity_Level')!r} is not 1-5")
        start, end = gtr._num(record.get("Start_Timestamp")), gtr._num(record.get("End_Timestamp"))
        if start is None or end is None or start < 0 or start >= end:
            problems.append(f"{where}: window {start}-{end} is not a valid start < end")
        elif clip and clip.get("duration_seconds") and end > clip["duration_seconds"] + TIME_TOLERANCE_SECONDS:
            problems.append(f"{where}: end {end:g} s is past the clip's {clip['duration_seconds']} s")
        duration = gtr._num(record.get("Duration"))
        if duration is not None and start is not None and end is not None and duration != end - start:
            problems.append(f"{where}: duration {duration:g} is not end - start")
        if not str(record.get("Description") or "").strip():
            problems.append(f"{where}: empty description")
        if record.get("Out_Of_Taxonomy") and not record.get("Nearest_Type"):
            problems.append(f"{where}: out of taxonomy without a nearest type")
    entities: dict[str, set] = {}
    for sheet, pattern in ID_PATTERNS.items():
        spec = gtr.SHEETS[sheet]
        seen = Counter()
        for record in records[sheet]:
            incident_id = gtr._clean(record.get(spec["incident"]))
            item_id = gtr._clean(record.get(spec["id"]))
            where = f"{sheet} {incident_id} {item_id}"
            seen[(incident_id, item_id)] += 1
            if incident_id not in incidents:
                problems.append(f"{where}: no such incident")
            if not re.fullmatch(pattern, str(record.get(spec["id"]) or "")):  # untrimmed: ids must be exact
                problems.append(f"{where}: id is not {pattern}")
            if sheet == "gt_entities":
                entities.setdefault(incident_id, set()).add(item_id)
                if str(record.get("Type") or "").strip().lower() not in ENTITY_TYPES:
                    problems.append(f"{where}: entity type {record.get('Type')!r}")
            if sheet == "gt_instruments" and gtr._num(record.get("Threat_Level")) not in (1, 2, 3, 4, 5):
                problems.append(f"{where}: threat {record.get('Threat_Level')!r} is not 1-5")
            if not str(record.get("Name" if sheet != "gt_entities" else "Type") or "").strip():
                problems.append(f"{where}: empty name")
        problems += [f"{sheet} {i} {r}: duplicate id" for (i, r), n in sorted(seen.items()) if n > 1]
    for record in records["gt_instruments"]:
        holder = gtr._clean(record.get("Entity_ID"))
        incident_id = gtr._clean(record.get("Incident_ID (P_key, F_key)"))
        if holder and holder not in entities.get(incident_id, set()):
            problems.append(f"gt_instruments {incident_id} {record.get('Instrument_ID (P_key)')}: holder {holder!r} "
                            "is not an entity of the incident")
    missing = sorted(c["incident_id"] for c in manifest["clips"] if c["incident_id"] not in incidents)
    if missing:
        problems.append(f"clips without a ground-truth incident: {', '.join(missing)}")
    return problems


def split_v2(split_manifests: list[dict]) -> dict:
    """``split-v2``: the existing seeded partition, renamed dev/test, membership unchanged."""
    dev, test, by_category = [], [], {}
    for split in sorted(split_manifests, key=lambda s: s["category"]):
        d = sorted(canonical_basename(f).split("_x264")[0] for f in split["few_shot_demo_videos"])
        t = sorted(canonical_basename(f).split("_x264")[0] for f in split["evaluation_videos"])
        by_category[split["category"]] = {"dev": d, "test": t}
        dev += d
        test += t
    return {"version": SPLIT_VERSION, "seed": sorted({s["seed"] for s in split_manifests}),
            "rule": "dev = the former few-shot clips, test = the evaluation clips of each seeded split_<category>.json",
            "dev": sorted(dev), "test": sorted(test), "by_category": by_category}


def split_problems(split: dict, records: dict[str, list[dict]], *, expected=(25, 55)) -> list[str]:
    problems = []
    gt_ids = {gtr._clean(r["Incident_ID (P_key)"]): r for r in records["gt_incidents"]}
    dev, test = set(split["dev"]), set(split["test"])
    if (len(dev), len(test)) != tuple(expected):
        problems.append(f"split is {len(dev)} dev / {len(test)} test, not {expected[0]} / {expected[1]}")
    if dev & test:
        problems.append(f"in both dev and test: {sorted(dev & test)}")
    if (dev | test) != set(gt_ids):
        problems.append(f"split and ground truth differ: {sorted((dev | test) ^ set(gt_ids))}")
    for category, members in split["by_category"].items():
        for incident_id in members["dev"] + members["test"]:
            record = gt_ids.get(incident_id)
            label = str((record or {}).get("Type") or "")
            label = gtr.LEGACY_TYPE_LABELS.get(label.strip().lower(), label)
            if record and label.strip().lower() != category.strip().lower():
                problems.append(f"{incident_id}: split category {category!r}, ground-truth type {record.get('Type')!r}")
    return problems


def blocking_issues(entries: list[gtc.Entry], schema: list[str], split: list[str]) -> list[str]:
    issues = []
    pending = [e.change_id for e in entries if e.status == "Pending" and e.change_type != "informational"]
    if pending:
        issues.append(f"{len(pending)} entries still Pending (never treated as Approved): {', '.join(pending[:10])}"
                      + (" …" if len(pending) > 10 else ""))
    issues += gtc.consistency_problems(entries)
    unusable = [e.change_id for e in entries if e.status == "Approved" and e.problems and e.accepted_value is None]
    if unusable:
        issues.append(f"approved entries whose AI proposal is invalid and that have no accepted value: {unusable}")
    issues += [f"schema: {p}" for p in schema]
    issues += [f"split: {p}" for p in split]
    return issues


def apply_exclusions(records: dict[str, list[dict]], split: dict, exclusions: list[str]):
    """Drop approved excluded incidents from every sheet and both split halves."""
    excluded = set(exclusions)
    out = {}
    for sheet, spec in gtr.SHEETS.items():
        out[sheet] = [r for r in records[sheet] if gtr._clean(r.get(spec["incident"])) not in excluded]
    split = {**split, "dev": [i for i in split["dev"] if i not in excluded],
             "test": [i for i in split["test"] if i not in excluded], "excluded": sorted(excluded)}
    return out, split


def mark_uncertain(records: dict[str, list[dict]], entries: list[gtc.Entry]) -> None:
    """A13: a record whose open question a person settled by confirming the original, while the AI
    reviewer called it uncertain, carries ``Uncertain`` (unscored)."""
    flagged = {e.change_id for e in entries if e.status == "Approved" and not e.applied
               and (e.ai or {}).get("decision") == "uncertain"}
    for sheet_records in records.values():
        for record in sheet_records:
            record["Uncertain"] = bool(flagged & set(record.get("_change_ids") or []))


def freeze_status(issues: list[str], approval: dict | None, *, workbook_sha256: str, records_sha256: str,
                  exclusions: list[str]) -> tuple[str, list[str]]:
    """``("frozen", [])`` only with no blocking issue and an approval naming exactly this candidate."""
    reasons = list(issues)
    if approval is None:
        reasons.append("no approval record: the final annotations and exclusions have not been approved")
    else:
        expected = {"version": VERSION, "candidate_workbook_sha256": workbook_sha256,
                    "records_sha256": records_sha256, "exclusions": sorted(exclusions)}
        for key, value in expected.items():
            if (sorted(approval.get(key) or []) if key == "exclusions" else approval.get(key)) != value:
                reasons.append(f"approval record {key} does not match this candidate")
        for key in ("approved_by", "approved_at"):
            if not approval.get(key):
                reasons.append(f"approval record has no {key}")
    return ("frozen" if not reasons else "candidate"), reasons


# --- reading ---------------------------------------------------------------------------------

def read_frozen(directory: Path, *, allow_candidate: bool = False) -> dict:
    """``ground_truth.json`` after verifying every file against ``MANIFEST.json``."""
    manifest_path = directory / "MANIFEST.json"
    if not manifest_path.exists():
        raise FrozenGroundTruthError(f"{directory}: no MANIFEST.json")
    manifest = json.loads(manifest_path.read_text())
    for name in FILES:
        path = directory / name
        if not path.exists() or sha256_bytes(path.read_bytes()) != manifest["files"].get(name):
            raise FrozenGroundTruthError(f"{directory / name}: missing or changed since it was written")
    if manifest.get("status") != "frozen" and not allow_candidate:
        raise FrozenGroundTruthError(
            f"{directory} is a {manifest.get('status')!r}, not frozen ground truth: "
            f"{'; '.join(manifest.get('blocking') or [])[:500]}")
    data = json.loads((directory / "ground_truth.json").read_text())
    data["split"] = json.loads((directory / "split-v2.json").read_text())
    data["manifest"] = manifest
    return data
