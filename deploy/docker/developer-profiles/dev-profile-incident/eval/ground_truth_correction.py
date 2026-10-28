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

"""AI-assisted ground-truth correction and human review (PR 4), on top of the PR 3 audit.

Pure functions; the scripts ``gt_review_packet.py`` and ``gt_candidate_build.py`` do the I/O.

- ``verify_mechanical`` re-checks a ``verified_correction`` from the source workbook and the
  dataset manifest **without** the audit's rule code, so an audit bug cannot approve itself.
  Only entries that pass are applied automatically (status ``Auto-verified``).
- ``validate_proposal`` checks an AI reviewer's video-based proposal: a decision, evidence
  timestamps that exist in the cited contact sheet, a confidence and full provenance. An AI
  proposal is never applied by itself: it stays ``Pending`` until a person approves it.
- ``resolve`` combines the audit, the carried-forward human decisions, the verification and
  the AI proposals into one entry per change, with what (if anything) is applied.
- ``apply_to_records`` builds the corrected records from the **source** records plus the
  applied entries only. The source is never edited; the same inputs always give the same output.
- ``guard_inputs`` keeps the correction independent of the system under test: nothing under
  the results, experiment-prompt or prediction locations may feed the review.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import ground_truth_review as gtr
from dataset_manifest import canonical_basename

CORRECTION_PROMPT_VERSION = "gt-correction-v1.0"
STATUSES = ("Pending", "Approved", "Rejected", "Auto-verified", "Informational", "AI-Accepted", "AI-Rejected",
            "AI-Modified", "AI-Unresolved")
# AI-assisted adjudication (gt-adjudication-v1.0, authorised by the owner): never a human decision.
ADJUDICATION_STATUS = {"ACCEPT": "AI-Accepted", "REJECT": "AI-Rejected", "MODIFY": "AI-Modified",
                       "UNRESOLVED": "AI-Unresolved"}
ADJUDICATION_PROMPT_VERSION = "gt-adjudication-v1.0"
ADJUDICATION_PROVENANCE = "AI-assisted, not human-reviewed"
IMPACT = ("low", "medium", "high")
LEVEL_FIELDS = ("Severity_Level", "Threat_Level")
# Fields no entry may ever change, whatever its status or accepted value (user decision 2026-10-28).
PROTECTED_FIELDS = ("Filename",)
HUMAN_DECISIONS = ("Approved", "Rejected")
AI_DECISIONS = ("propose_change", "keep_original", "uncertain")
CONFIDENCE = ("high", "medium", "low")
# Paths the correction must never read: model outputs, scores, experiment prompts, VSS predictions.
FORBIDDEN_INPUT_PARTS = (("eval_data", "results"), ("contracts", "experiments"), ("eval", "experiments"),
                         ("eval_reproducibility", "runs"))
NOTE_FIELDS = ("Out_Of_Taxonomy", "Nearest_Type")  # R22 proposals set these incident columns (methodology v1.0, Option C)


class IndependenceError(ValueError):
    """A correction input lies under a location that holds system-under-test outputs."""


def guard_inputs(paths) -> None:
    for path in paths:
        parts = Path(path).resolve().parts
        for forbidden in FORBIDDEN_INPUT_PARTS:
            if any(parts[i:i + len(forbidden)] == forbidden for i in range(len(parts))):
                raise IndependenceError(f"{path}: ground-truth correction must not read {'/'.join(forbidden)}/")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --- independent verification of mechanical corrections -----------------------------------

def _documented(sheet: str, record: dict) -> tuple:
    return tuple(gtr._clean(record.get(column)) for column in gtr.SHEETS[sheet]["columns"])


def verify_mechanical(change: gtr.Change, workbook_values, manifest: dict) -> tuple[bool, str]:
    """``(ok, detail)``: does the source itself prove this ``verified_correction``?"""
    ws = workbook_values[change.sheet]
    header = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    filenames = {clip["filename"] for clip in manifest["clips"]}
    row_values = [c.value for c in ws[change.row]] if change.row and change.row >= 2 else []
    record = dict(zip(header, row_values))
    if change.rule == "R01":
        original = str(record.get("Filename") or "").strip()
        ok = (original == change.original_value and original.endswith("_demo.mp4")
              and change.proposed_value == original[: -len("_demo.mp4")] + ".mp4" and change.proposed_value in filenames)
        return ok, "source cell ends in _demo.mp4; the plain name is a dataset-manifest-v1 clip" if ok else "R01 mismatch"
    if change.rule == "R03":
        value = record.get(change.field)
        ok = isinstance(value, str) and value == change.original_value and value != value.strip() \
            and change.proposed_value == value.strip()
        return ok, "source cell differs from its trimmed value only by whitespace" if ok else "R03 mismatch"
    if change.rule == "R05":
        column = int(str(change.field).split()[1])
        value = ws.cell(change.row, column).value
        ok = column > len(gtr.SHEETS[change.sheet]["columns"]) and value == change.original_value \
            and change.proposed_value in (None, "")
        return ok, f"cell is in column {column}, right of the documented columns" if ok else "R05 mismatch"
    if change.rule == "R02":
        this = _documented(change.sheet, {**record, "Filename": canonical_basename(str(record.get("Filename") or ""))})
        for earlier in range(2, change.row):
            other = dict(zip(header, [c.value for c in ws[earlier]]))
            other["Filename"] = canonical_basename(str(other.get("Filename") or ""))
            if _documented(change.sheet, other) == this:
                return True, f"identical in every documented column to row {earlier}"
        return False, "no identical earlier row"
    if change.rule == "R28":
        start, end = gtr._num(record.get("Start_Timestamp")), gtr._num(record.get("End_Timestamp"))
        derived = str(change.proposed_value).replace(" ", "") == "=End_Timestamp-Start_Timestamp" \
            or gtr._num(change.proposed_value) == (end - start if start is not None and end is not None else None)
        ok = start is not None and end is not None and gtr._num(record.get("Duration")) != end - start and derived
        return ok, "the source Duration is not End - Start; the proposal derives it" if ok else "R28 mismatch"
    return False, f"no independent check for {change.rule}"


# --- AI proposals ---------------------------------------------------------------------------

def load_proposals(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    proposals = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            proposals[record["change_id"]] = record
    return proposals


def validate_proposal(proposal: dict, change: gtr.Change, frames: dict | None) -> list[str]:
    """Problems with one AI proposal (empty when valid). ``frames`` is the clip's ``frames.json``."""
    problems = []
    decision = proposal.get("decision")
    if decision not in AI_DECISIONS:
        problems.append(f"decision {decision!r} not in {AI_DECISIONS}")
    if proposal.get("confidence") not in CONFIDENCE:
        problems.append(f"confidence {proposal.get('confidence')!r} not in {CONFIDENCE}")
    for key in ("incident_id", "record_id", "field"):
        if str(proposal.get(key)) != str(getattr(change, key)):
            problems.append(f"{key} {proposal.get(key)!r} does not match the change ({getattr(change, key)!r})")
    value = proposal.get("proposed_value")
    if decision == "propose_change":
        if value in (None, ""):
            problems.append("propose_change needs a proposed_value")
        elif change.rule == "R22" and not (isinstance(value, dict) and set(value) == set(NOTE_FIELDS)):
            problems.append(f"R22 proposed_value must set exactly {NOTE_FIELDS}")
        elif change.rule != "R22" and value == change.original_value:
            problems.append("proposed_value equals the original")
    elif value not in (None, ""):
        problems.append(f"{decision} must not carry a proposed_value")
    if not str(proposal.get("explanation") or "").strip():
        problems.append("explanation is empty")
    evidence = proposal.get("evidence") or []
    if decision in ("propose_change", "keep_original") and not evidence:
        problems.append("a decision needs at least one evidence timestamp")
    sheets = {s["file"]: s for s in (frames or {}).get("sheets", [])}
    for item in evidence:
        sheet = sheets.get(item.get("sheet"))
        if sheet is None:
            problems.append(f"evidence sheet {item.get('sheet')!r} is not in frames.json")
        elif not any(abs(float(item.get("t", -1)) - t) <= 0.6 for t in sheet["times"]):
            problems.append(f"evidence time {item.get('t')} is not a tile of {item.get('sheet')}")
        elif (proposal.get("frames_sha256") or {}).get(item["sheet"]) not in (None, sheet["sha256"]):
            problems.append(f"{item['sheet']} changed since the proposal was made")
    for key in ("reviewer", "correction_prompt", "correction_prompt_sha256", "guidelines"):
        if not proposal.get(key):
            problems.append(f"{key} is missing")
    if proposal.get("correction_prompt") not in (None, CORRECTION_PROMPT_VERSION):
        problems.append(f"correction_prompt {proposal.get('correction_prompt')!r} is not {CORRECTION_PROMPT_VERSION}")
    return problems


# --- AI-assisted adjudication (gt-adjudication-v1.0) --------------------------------------------

def load_adjudication(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            if record["change_id"] in records:
                raise ValueError(f"{record['change_id']} is adjudicated twice")
            records[record["change_id"]] = record
    return records


def _tile_times(evidence_file: Path) -> list[float] | None:
    """Tile times of a cited image: a close-up's sidecar JSON, or the clip's ``frames.json`` for a contact sheet."""
    sidecar = evidence_file.with_suffix(".json")
    if sidecar.exists():
        return json.loads(sidecar.read_text()).get("times")
    frames = evidence_file.parent / "frames.json"
    if frames.exists():
        sheet = next((s for s in json.loads(frames.read_text())["sheets"] if s["file"] == evidence_file.name), None)
        return sheet["times"] if sheet else None
    return None


def validate_adjudication(record: dict, change: gtr.Change, proposal: dict | None, *, base: Path,
                          prompt_sha256: str) -> list[str]:
    """Problems with one adjudication (empty when it may be applied)."""
    problems = []
    decision = record.get("decision")
    if decision not in ADJUDICATION_STATUS:
        return [f"decision {decision!r} not in {tuple(ADJUDICATION_STATUS)}"]
    for key in ("incident_id", "record_id", "field", "rule"):
        if str(record.get(key)) != str(getattr(change, key)):
            problems.append(f"{key} {record.get(key)!r} does not match the change ({getattr(change, key)!r})")
    ai_decision = (proposal or {}).get("decision")
    value = record.get("final_value")
    if decision == "REJECT" and ai_decision == "keep_original":
        problems.append("REJECT of a keep_original proposal: use ACCEPT (keep) or MODIFY")
    if decision == "ACCEPT" and ai_decision == "uncertain":
        problems.append("ACCEPT of an uncertain proposal: use REJECT, MODIFY or UNRESOLVED")
    if decision == "ACCEPT" and change.change_type == "needs_video_review":
        expected = proposal.get("proposed_value") if ai_decision == "propose_change" else None
        if value != expected:
            problems.append("ACCEPT must carry the AI proposal's value unchanged (or null when it kept the original)")
    if decision in ("REJECT", "UNRESOLVED") and value is not None:
        problems.append(f"{decision} keeps the original: final_value must be null")
    if decision == "MODIFY":
        if change.rule == "R10":
            problems.append("a reclassification (R10) is accepted or rejected as a whole, never modified")
        elif value in (None, ""):
            problems.append("MODIFY needs a final_value")
        elif change.rule == "R22":
            if not (isinstance(value, dict) and set(value) == set(NOTE_FIELDS)):
                problems.append(f"R22 final_value must set exactly {NOTE_FIELDS}")
        elif value == change.original_value or (gtr._num(value) is not None
                                                  and gtr._num(value) == gtr._num(change.original_value)):
            problems.append("MODIFY repeats the original value")
        if change.field in LEVEL_FIELDS and value not in (1, 2, 3, 4, 5):
            problems.append(f"{change.field} must be a whole number 1-5")
    if change.field in PROTECTED_FIELDS and decision in ("ACCEPT", "MODIFY"):
        problems.append(f"{change.field} is protected and is never modified")
    if record.get("impact") not in IMPACT:
        problems.append(f"impact {record.get('impact')!r} not in {IMPACT}")
    if record.get("video_verified") is not True:
        problems.append("every adjudication must be video-verified (a text-only assessment is not verification)")
    evidence = record.get("evidence") or []
    if not evidence:
        problems.append("no evidence frames cited")
    for item in evidence:
        path = base / str(item.get("file", ""))
        times = _tile_times(path) if path.exists() else None
        if times is None:
            problems.append(f"evidence file {item.get('file')!r} does not exist or has no tile times")
        elif not any(abs(float(item.get("t", -999)) - t) <= 0.6 for t in times):
            problems.append(f"evidence time {item.get('t')} is not a tile of {item.get('file')}")
    if record.get("impact") == "high" and not any("gt_adjudication" in str(e.get("file")) for e in evidence):
        problems.append("a high-impact decision needs a close-up (gt_frame_detail.py), not only a contact sheet")
    if record.get("provenance") != ADJUDICATION_PROVENANCE:
        problems.append(f"provenance must be {ADJUDICATION_PROVENANCE!r}")
    if record.get("adjudication_prompt") != ADJUDICATION_PROMPT_VERSION or \
            record.get("adjudication_prompt_sha256") != prompt_sha256:
        problems.append("adjudication prompt version or SHA-256 does not match gt-adjudication-v1.0")
    if not str(record.get("justification") or "").strip() or not str(record.get("blind_assessment") or "").strip():
        problems.append("justification and blind_assessment are required")
    return problems


def adjudication_problems(entries: list[Entry]) -> list[str]:
    """Cross-entry checks: linked entries decided alike."""
    problems = []
    by_group: dict[tuple, set] = {}
    for entry in entries:
        if entry.rule == "R10" and entry.adjudication:
            by_group.setdefault((entry.incident_id, entry.rule), set()).add(entry.adjudication["decision"])
    for (incident_id, rule), decisions in by_group.items():
        if len(decisions) > 1:
            problems.append(f"{incident_id} {rule}: the reclassification's entries were adjudicated differently")
    return problems


# --- prior decisions (carried forward, never discarded) ----------------------------------------

def read_change_log(workbook) -> list[dict]:
    """The ``Change Log`` rows of a review or candidate workbook, as ``{header: value}``."""
    ws = workbook["Change Log"]
    header = [str(c.value or "").strip() for c in ws[1]]
    return [dict(zip(header, row)) for row in ws.iter_rows(min_row=2, values_only=True) if row and row[0]]


def check_carry_forward(changes: list[gtr.Change], prior_log: list[dict]) -> list[str]:
    """The prior workbook must describe the same findings (same id, record, field and original)."""
    problems = []
    by_id = {str(row["Change ID"]): row for row in prior_log}
    if set(by_id) != {c.change_id for c in changes}:
        problems.append(f"change ids differ: {sorted(set(by_id) ^ {c.change_id for c in changes})[:5]}")
    for change in changes:
        row = by_id.get(change.change_id)
        if row is None:
            continue
        expected = (change.incident_id, str(change.record_id), change.field, change.rule)
        found = (row.get("Incident ID"), str(row.get("Record ID")), row.get("Field"), row.get("Rule"))
        if expected != found:
            problems.append(f"{change.change_id}: prior workbook has {found}, the audit gives {expected}")
    return problems


# --- resolution ----------------------------------------------------------------------------------

@dataclass
class Entry:
    change_id: str
    rule: str
    change_type: str
    sheet: str
    row: int
    incident_id: str
    record_id: str
    field: str
    original_value: object
    proposed_value: object
    status: str = "Pending"
    reviewer: str | None = None
    notes: str | None = None
    accepted_value: object = None
    verification: str = ""
    ai: dict | None = None
    applied: bool = False
    applied_value: object = None
    carried_from: str | None = None
    problems: list = field(default_factory=list)
    adjudication: dict | None = None


def _accepted(row: dict | None):
    value = (row or {}).get("Accepted value")
    return None if value in (None, "") else value


def resolve(changes: list[gtr.Change], *, prior: dict[str, dict] | None, prior_name: str | None,
            verification: dict[str, tuple[bool, str]], proposals: dict[str, dict],
            proposal_problems: dict[str, list[str]], adjudication: dict[str, dict] | None = None) -> list[Entry]:
    """One entry per change. A human decision always wins, then a valid AI adjudication; nothing uncertain is applied."""
    entries = []
    for change in changes:
        row = (prior or {}).get(change.change_id)
        human = str((row or {}).get("Review status") or "").strip()
        entry = Entry(change.change_id, change.rule, change.change_type, change.sheet, change.row, change.incident_id,
                      str(change.record_id), change.field, change.original_value, change.proposed_value,
                      reviewer=(row or {}).get("Reviewer") or None, notes=(row or {}).get("Review notes") or None,
                      accepted_value=_accepted(row), carried_from=prior_name if row else None)
        ok, detail = verification.get(change.change_id, (False, ""))
        entry.verification = ("passed: " if ok else "failed: ") + detail if change.change_type == "verified_correction" \
            else "not applicable (needs a person)"
        proposal = proposals.get(change.change_id)
        if proposal is not None:
            entry.ai = proposal
            entry.problems = list(proposal_problems.get(change.change_id, []))
            if not entry.problems and proposal["decision"] == "propose_change" \
                    and change.change_type == "needs_video_review":
                entry.proposed_value = proposal["proposed_value"]
        judged = (adjudication or {}).get(change.change_id)
        if judged is not None:
            entry.adjudication = judged
        if human in HUMAN_DECISIONS:
            entry.status = human
        elif judged is not None and not judged.get("_problems"):
            entry.status = ADJUDICATION_STATUS[judged["decision"]]
        elif change.change_type == "verified_correction" and ok:
            entry.status = "Auto-verified"
        elif change.change_type == "informational":
            entry.status = "Informational"  # recorded only: nothing to decide, never applied
        entry.applied, entry.applied_value = _applied(entry)
        entries.append(entry)
    return entries


def _applied(entry: Entry) -> tuple[bool, object]:
    if entry.status == "AI-Modified" and entry.field not in PROTECTED_FIELDS:
        return True, entry.adjudication["final_value"]
    if entry.status == "AI-Accepted":
        # The AI proposal as adjudicated: its value for a video-review entry (none when it kept the original),
        # the audit's own proposal for a rule-based one (the R10 reclassification).
        if entry.field in PROTECTED_FIELDS or entry.change_type == "informational":
            return False, None
        if entry.change_type == "needs_video_review":
            return (False, None) if entry.problems or entry.proposed_value is None else (True, entry.proposed_value)
        return True, entry.proposed_value
    if entry.status not in ("Approved", "Auto-verified") or entry.change_type == "informational":
        return False, None
    if entry.field in PROTECTED_FIELDS:
        return False, None
    if entry.accepted_value is not None and entry.status == "Approved":
        return True, _parse_accepted(entry.accepted_value)
    if entry.change_type == "needs_video_review":
        # Approving a review entry without a usable proposal confirms the original: nothing changes.
        if entry.problems or entry.proposed_value is None:
            return False, None
    return True, entry.proposed_value


def _parse_accepted(value):
    if isinstance(value, str) and value.strip().startswith("{"):
        return json.loads(value)
    return value


def consistency_problems(entries: list[Entry]) -> list[str]:
    """Linked entries must be decided together (a reclassification removes one row and adds another)."""
    problems = []
    by_group: dict[tuple, list[Entry]] = {}
    for entry in entries:
        if entry.rule == "R10":
            by_group.setdefault((entry.incident_id, entry.rule), []).append(entry)
    for (incident_id, rule), group in by_group.items():
        if len({e.applied for e in group}) > 1:
            problems.append(f"{incident_id} {rule}: {', '.join(e.change_id for e in group)} must be approved or "
                            "rejected together")
    return problems


# --- applying ----------------------------------------------------------------------------------

def apply_to_records(rows: dict[str, list[tuple[int, dict]]], entries: list[Entry]) -> dict[str, list[dict]]:
    """Corrected records: the source's documented columns with only the applied entries.

    Each record keeps ``_source_row`` and ``_change_ids`` for provenance. Removed rows are
    dropped, new rows appended; nothing is renumbered. Deterministic for the same inputs.
    """
    out: dict[str, list[dict]] = {}
    applied = [e for e in entries if e.applied]
    for sheet, spec in gtr.SHEETS.items():
        records = []
        for excel_row, record in rows[sheet]:
            clean = {column: record.get(column) for column in spec["columns"]}
            if sheet == "gt_incidents":
                for note in NOTE_FIELDS:
                    clean[note] = record.get(note)
            clean["_source_row"] = excel_row
            clean["_change_ids"] = []
            records.append(clean)
        by_row = {r["_source_row"]: r for r in records}
        removed = set()
        for entry in applied:
            if entry.sheet != sheet:
                continue
            target = by_row.get(entry.row)
            if entry.field == "(new row)":
                new = {column: copy.deepcopy(entry.applied_value).get(column) for column in spec["columns"]}
                new.update({"_source_row": None, "_change_ids": [entry.change_id]})
                records.append(new)
                continue
            if target is None:
                raise ValueError(f"{entry.change_id}: no source row {entry.row} in {sheet}")
            target["_change_ids"].append(entry.change_id)
            if entry.rule == "R02" or (entry.field == "(row)" and str(entry.applied_value).startswith("remove")):
                removed.add(entry.row)
            elif entry.rule == "R05":
                pass  # the stray cell is outside the documented columns, which are all a record keeps
            elif entry.rule == "R22":
                target.update(entry.applied_value)
            elif entry.field in PROTECTED_FIELDS:
                raise ValueError(f"{entry.change_id}: {entry.field} is protected and is never modified")
            elif entry.field in spec["columns"]:
                target[entry.field] = entry.applied_value
            else:
                raise ValueError(f"{entry.change_id}: cannot apply field {entry.field!r}")
        out[sheet] = [r for r in records if r["_source_row"] not in removed]
    return out


def records_digest(records: dict[str, list[dict]]) -> str:
    return hashlib.sha256(json.dumps(records, sort_keys=True, default=str).encode()).hexdigest()


def entries_digest(entries: list[Entry]) -> str:
    rows = [{k: v for k, v in asdict(e).items() if k not in ("reviewer", "notes")} for e in entries]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def incident_window(rows: dict[str, list[tuple[int, dict]]], incident_id: str) -> tuple[float | None, float | None]:
    for _, record in rows["gt_incidents"]:
        if gtr._clean(record.get("Incident_ID (P_key)")) == incident_id:
            return gtr._num(record.get("Start_Timestamp")), gtr._num(record.get("End_Timestamp"))
    return None, None


SAFE_ID = re.compile(r"^[A-Za-z]+[0-9]+$")
