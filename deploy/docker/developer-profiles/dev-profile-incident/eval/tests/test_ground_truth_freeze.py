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

"""Ground-truth freeze (PR 5): validation, split-v2, blocking rules, approval gate and the verified loader."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import eval_gt_schema  # noqa: E402
import ground_truth_correction as gtc  # noqa: E402
import ground_truth_freeze as gtf  # noqa: E402
import gt_candidate_build  # noqa: E402
import gt_freeze  # noqa: E402
import gt_review_build  # noqa: E402
import review_backup  # noqa: E402
from test_ground_truth_review import _decide, _manifest, _workbook  # noqa: E402

MANIFEST = {"clips": [{"incident_id": "Assault001", "filename": "Assault001_x264.mp4", "duration_seconds": 30.0},
                      {"incident_id": "Burglary002", "filename": "Burglary002_x264.mp4", "duration_seconds": 20.0}]}


def _records():
    return {
        "gt_incidents": [
            {"Filename": "Assault001_x264.mp4", "Incident_ID (P_key)": "Assault001", "Type": "Assault",
             "Start_Timestamp": 2, "End_Timestamp": 9, "Duration": 7, "Description": "Two people fight.",
             "Severity_Level": 3},
            {"Filename": "Burglary002_x264.mp4", "Incident_ID (P_key)": "Burglary002", "Type": "Burglary",
             "Start_Timestamp": 0, "End_Timestamp": 20, "Duration": 20, "Description": "A door is forced.",
             "Severity_Level": 2},
        ],
        "gt_entities": [{"Filename": "Assault001_x264.mp4", "Incident_ID (P_key, F_key)": "Assault001",
                         "Entity_ID (P_key)": "E1", "Type": "human", "Description": "Person in red"}],
        "gt_instruments": [{"Filename": "Assault001_x264.mp4", "Incident_ID (P_key, F_key)": "Assault001",
                            "Instrument_ID (P_key)": "I1", "Entity_ID": "E1", "Name": "stick",
                            "Description": "Wooden stick", "Threat_Level": 2}],
        "gt_assets": [{"Filename": "Burglary002_x264.mp4", "Incident_ID (P_key, F_key)": "Burglary002",
                       "Asset_ID (P_key)": "A1", "Name": "door", "Description": "Shop door"}],
    }


def test_valid_records_have_no_schema_problems():
    assert gtf.schema_problems(_records(), MANIFEST) == []


@pytest.mark.parametrize("sheet, index, field, value, problem", [
    ("gt_incidents", 0, "Type", "Shooting", "not one of the five"),
    ("gt_incidents", 0, "Severity_Level", 6, "not 1-5"),
    ("gt_incidents", 0, "End_Timestamp", 1, "start < end"),
    ("gt_incidents", 0, "End_Timestamp", 40, "past the clip"),
    ("gt_incidents", 0, "Duration", 5, "end - start"),
    ("gt_incidents", 0, "Filename", "Other_x264.mp4", "not a dataset-manifest-v1 clip"),
    ("gt_incidents", 0, "Description", " ", "empty description"),
    ("gt_entities", 0, "Entity_ID (P_key)", "E1 ", "id is not"),
    ("gt_entities", 0, "Type", "vehicle", "entity type"),
    ("gt_instruments", 0, "Threat_Level", 0, "threat"),
    ("gt_instruments", 0, "Entity_ID", "E9", "holder"),
])
def test_schema_problems_are_found(sheet, index, field, value, problem):
    records = _records()
    records[sheet][index][field] = value
    assert any(problem in p for p in gtf.schema_problems(records, MANIFEST))


def test_a_clip_without_ground_truth_is_a_problem():
    records = _records()
    records["gt_incidents"].pop()
    records["gt_assets"].clear()
    assert any("clips without" in p for p in gtf.schema_problems(records, MANIFEST))


def _splits():
    return [{"category": "Assault", "seed": 42, "few_shot_demo_videos": ["Assault001_x264_demo.mp4"],
             "evaluation_videos": []},
            {"category": "Burglary", "seed": 42, "few_shot_demo_videos": [], "evaluation_videos": ["Burglary002_x264.mp4"]}]


def test_split_v2_keeps_membership_and_checks_consistency():
    split = gtf.split_v2(_splits())
    assert split["dev"] == ["Assault001"] and split["test"] == ["Burglary002"] and split["seed"] == [42]
    assert gtf.split_problems(split, _records(), expected=(1, 1)) == []
    assert gtf.split_problems(split, _records()) != []  # not 25/55
    both = copy.deepcopy(split)
    both["test"].append("Assault001")
    assert any("both" in p for p in gtf.split_problems(both, _records(), expected=(1, 2)))
    records = _records()
    records["gt_incidents"][1]["Type"] = "Assault"
    assert any("split category" in p for p in gtf.split_problems(split, records, expected=(1, 1)))


def _approval(**overrides):
    approval = {"version": gtf.VERSION, "candidate_workbook_sha256": "w" * 64, "records_sha256": "r" * 64,
                "exclusions": [], "approved_by": "a reviewer", "approved_at": "2026-11-01"}
    approval.update(overrides)
    return approval


def test_frozen_only_with_no_issue_and_a_matching_approval():
    kwargs = {"workbook_sha256": "w" * 64, "records_sha256": "r" * 64, "exclusions": []}
    assert gtf.freeze_status([], _approval(), **kwargs) == ("frozen", [])
    assert gtf.freeze_status([], None, **kwargs)[0] == "candidate"
    assert gtf.freeze_status(["1 entries still Pending"], _approval(), **kwargs)[0] == "candidate"
    for override in ({"records_sha256": "x" * 64}, {"candidate_workbook_sha256": "x" * 64}, {"exclusions": ["A"]},
                     {"approved_by": ""}, {"version": "ground-truth-v0.9"}):
        assert gtf.freeze_status([], _approval(**override), **kwargs)[0] == "candidate"


def test_pending_entries_block_and_are_never_treated_as_approved():
    entry = gtc.Entry("CL-0001", "R25", "needs_video_review", "gt_incidents", 2, "A", "A", "Description", "x", "y")
    assert any("Pending" in i for i in gtf.blocking_issues([entry], [], []))
    entry.status = "Approved"
    assert gtf.blocking_issues([entry], [], []) == []


def _write(directory: Path, status: str = "frozen") -> Path:
    files = {"ground_truth.json": gtf.canonical_json({"version": gtf.VERSION, "status": status, "sheets": _records()}),
             "split-v2.json": gtf.canonical_json(gtf.split_v2(_splits()))}
    directory.mkdir(parents=True)
    for name, content in files.items():
        (directory / name).write_bytes(content)
    (directory / "MANIFEST.json").write_text(json.dumps({"status": status, "blocking": [] if status == "frozen" else
                                                        ["1 entries still Pending"],
                                                        "files": {n: gtf.sha256_bytes(c) for n, c in files.items()}}))
    return directory


def test_loader_verifies_checksums_and_refuses_candidates(tmp_path):
    frozen = _write(tmp_path / "frozen")
    index = eval_gt_schema.load_frozen_gt_index(frozen)
    assert set(index["by_incident_id"]) == {"Assault001", "Burglary002"} and index["status"] == "frozen"
    assert index["by_incident_id"]["Assault001"]["p1_shaped"]["instruments"][0]["entity_id"] == "E1"
    candidate = _write(tmp_path / "candidate", status="candidate")
    with pytest.raises(gtf.FrozenGroundTruthError, match="not frozen"):
        eval_gt_schema.load_frozen_gt_index(candidate)
    assert eval_gt_schema.load_frozen_gt_index(candidate, allow_candidate=True)["status"] == "candidate"
    (frozen / "ground_truth.json").write_text((frozen / "ground_truth.json").read_text().replace("fight", "hug"))
    with pytest.raises(gtf.FrozenGroundTruthError, match="changed"):
        eval_gt_schema.load_frozen_gt_index(frozen)


def test_frozen_index_matches_the_workbook_index(tmp_path):
    source = _workbook(tmp_path / "source.xlsx")
    wb = openpyxl.load_workbook(source, data_only=True)
    from eval_ingest_gt import _sheet_rows, load_gt_incidents
    rows = {"gt_incidents": load_gt_incidents(wb), **{s: _sheet_rows(wb, s) for s in
                                                     ("gt_entities", "gt_instruments", "gt_assets")}}
    from_rows = eval_gt_schema.gt_index_from_rows(*rows.values())
    assert from_rows == eval_gt_schema.load_gt_index(source)


@pytest.fixture
def reviewed(tmp_path):
    source, manifest = _workbook(tmp_path / "source.xlsx"), _manifest(tmp_path / "manifest.json")
    gt_review_build.build(source, manifest, tmp_path / "review", "v0.1")
    proposals = tmp_path / "review" / "ai-proposals-v0.2.jsonl"
    proposals.write_text("")
    gt_candidate_build.build(source, manifest, tmp_path / "review" / "Ground Truth Review v0.1.xlsx", proposals,
                             tmp_path / "review", "v0.2", frames_dir=tmp_path / "frames")
    splits = []
    for category, demo, evaluation in (("Assault", ["Assault018_x264.mp4"], ["Animal004_x264.mp4"]),):
        path = tmp_path / f"split_{category}.json"
        path.write_text(json.dumps({"category": category, "seed": 42, "few_shot_demo_videos": demo,
                                    "evaluation_videos": evaluation}))
        splits.append(path)
    return source, manifest, tmp_path / "review" / "Ground Truth Candidate v0.2.xlsx", proposals, splits


def test_freeze_writes_a_blocked_candidate_and_leaves_inputs_alone(reviewed, tmp_path):
    source, manifest, candidate, proposals, splits = reviewed
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, candidate)}
    result = gt_freeze.freeze(source, manifest, candidate, proposals, splits, tmp_path / "gt",
                              frames_dir=tmp_path / "frames", report_dir=tmp_path / "report")
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source, candidate)} == before
    assert result["status"] == "candidate"
    assert any("Pending" in r for r in result["blocking"]) and any("approval" in r for r in result["blocking"])
    with pytest.raises(gtf.FrozenGroundTruthError):
        gtf.read_frozen(tmp_path / "gt" / gtf.VERSION)
    report = (tmp_path / "report" / f"{gtf.VERSION}-readiness.md").read_text()
    assert "zebra-striped umbrella" not in report and "annotator" not in report


def test_human_rejection_of_an_auto_verified_entry_is_honoured(reviewed, tmp_path):
    source, manifest, candidate, proposals, splits = reviewed
    _decide(candidate, row=2, status="Rejected")
    entries, _ = gt_freeze.corrected(source, json.loads(manifest.read_text()), candidate, proposals, tmp_path)
    first = entries[0]
    assert first.status == "Rejected" and not first.applied


def test_a_frozen_directory_is_never_overwritten(reviewed, tmp_path):
    source, manifest, candidate, proposals, splits = reviewed
    _write(tmp_path / "gt" / gtf.VERSION)
    with pytest.raises(review_backup.OverwriteRefusedError, match="frozen"):
        gt_freeze.freeze(source, manifest, candidate, proposals, splits, tmp_path / "gt", report_dir=None)


def test_tracked_split_v2_is_the_seeded_partition():
    root = Path(__file__).resolve().parents[1] / "eval_reproducibility"
    split = gtf.split_v2([json.loads(p.read_text()) for p in sorted(root.glob("split_*.json"))])
    assert (root / "split-v2.json").read_bytes() == gtf.canonical_json(split)
    assert (len(split["dev"]), len(split["test"])) == (25, 55) and not set(split["dev"]) & set(split["test"])
    assert all(len(members["dev"]) == 5 for members in split["by_category"].values())


def test_a_presentation_demo_filename_resolves_to_its_clip():
    records = _records()
    records["gt_incidents"][0]["Filename"] = "Assault001_x264_demo.mp4"
    assert gtf.schema_problems(records, MANIFEST) == []
