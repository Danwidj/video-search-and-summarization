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

"""eval_benchmark_export: per-video rows (failures kept), per-field model summaries, timing - read-only."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_benchmark_export as export  # noqa: E402


def _fields(passed: bool, *, start_err=0, desc=0.8):
    return {
        "type": {"expected": "assault", "predicted": "assault" if passed else None, "pass": passed},
        "severity_level": {"expected": 3, "predicted": 3 if passed else None, "pass": passed},
        "start_timestamp": {"expected": 10, "predicted": 10 + start_err if passed else None, "pass": passed},
        "end_timestamp": {"expected": 20, "predicted": 20 if passed else None, "pass": passed},
        "duration": {"expected": 10, "predicted": 10 - start_err if passed else None, "pass": passed},
        "description": {"expected": "x", "predicted": "x" if passed else None, "score": desc, "pass": desc >= 0.5},
    }


def _video(name, *, ok=True, core_ok=True, elapsed=10.0, error="", start_err=0, desc=0.8, failure_kind=None,
           core_codes=(), retries=0):
    attempts = [{"attempt": i + 1, "wait_before_s": 60.0 if i else 0.0,
                 "wait_reason": "rate_limit_cooldown" if i else None} for i in range(retries + 1)]
    return {
        "filename": name, "incident_id": name.split(".")[0], "r2_object_key": f"anomaly/assault/{name}",
        "video": {"size_bytes": 3_000_000, "duration_seconds": 30.0},
        "timing": {"p1_elapsed_s": elapsed if ok else None, "final_attempt_elapsed_s": elapsed, "started_at": "t"},
        "judge_calls": 1,
        "validation": {"core_violations": [{"code": c} for c in core_codes]},
        "p1_raw": {"ok": ok, "contract_ok": core_ok, "core_ok": core_ok, "finish_reason": "stop" if ok else None,
                   "error": error, "failure_kind": failure_kind,
                   "usage": {"prompt_tokens": 100, "completion_tokens": 50} if ok else {},
                   "rate_limit": {"attempt_count": retries + 1, "rate_limit_retries": retries, "attempts": attempts}},
        "incident_field_scores": _fields(ok and core_ok, start_err=start_err, desc=desc if ok and core_ok else 0.0),
    }


def _payloads():
    return [
        {"category": "Assault", "model_id": "m1", "prompt_version": "incident-contract-v2",
         "validation_policy": "core-scored-v1", "benchmark": {"incident_only": True},
         "videos": [_video("A1.mp4", elapsed=10.0, start_err=2, retries=1),
                    _video("A2.mp4", elapsed=20.0, core_ok=False, core_codes=["SCHEMA_VIOLATION"]),
                    _video("A3.mp4", ok=False, elapsed=300.0, error="ReadTimeout: read timed out",
                           failure_kind="timeout"),
                    _video("A5.mp4", ok=False, elapsed=7.0, error="429", failure_kind="rate_limited", retries=2),
                    _video("A6.mp4", elapsed=15.0, core_ok=False, core_codes=["INVALID_JSON"])],
         "skipped_videos": [{"filename": "A4.mp4", "reason": "no R2 object found"}]},
        {"category": "Assault", "model_id": "m2", "prompt_version": "incident-contract-v2",
         "validation_policy": "core-scored-v1", "benchmark": {"incident_only": True},
         "videos": [_video("A1.mp4", elapsed=5.0), _video("A2.mp4", elapsed=7.0),
                    _video("A3.mp4", ok=False, elapsed=1.0, error="HTTP 500", failure_kind="http_error")],
         "skipped_videos": [{"filename": "A4.mp4", "reason": "no R2 object found"}]},
    ]


def _summary():
    rows = export.build_rows(_payloads(), {"A4.mp4": {"size_bytes": 1_000_000, "duration_seconds": 8.0}})
    return rows, export.build_summary(rows, _payloads(), Path("runs/x"))


def test_every_pair_is_a_row_with_its_outcome():
    rows, _ = _summary()
    outcomes = {(r["filename"], r["model_id"]): r["outcome"] for r in rows}
    assert outcomes == {
        ("A1.mp4", "m1"): "scored", ("A2.mp4", "m1"): "contract_invalid", ("A3.mp4", "m1"): "timeout",
        ("A4.mp4", "m1"): "not_attempted", ("A5.mp4", "m1"): "rate_limited", ("A6.mp4", "m1"): "parse_failure",
        ("A1.mp4", "m2"): "scored", ("A2.mp4", "m2"): "scored", ("A3.mp4", "m2"): "http_error",
        ("A4.mp4", "m2"): "not_attempted",
    }
    quality = {(r["filename"], r["model_id"]) for r in rows if r["model_quality_row"]}
    assert quality == {("A1.mp4", "m1"), ("A2.mp4", "m1"), ("A6.mp4", "m1"), ("A1.mp4", "m2"), ("A2.mp4", "m2")}
    a5 = next(r for r in rows if r["filename"] == "A5.mp4")
    assert a5["processing_time_s"] is None and a5["final_attempt_time_s"] == 7.0
    assert a5["attempt_count"] == 3 and a5["rate_limit_retries"] == 2 and a5["rate_limit_wait_s"] == 120.0
    a4 = next(r for r in rows if r["filename"] == "A4.mp4")
    assert a4["video_size_mb"] == pytest.approx(1.0) and a4["video_duration_s"] == 8.0  # from dataset_stats


def test_fields_cover_model_outputs_only_and_invalid_outputs_are_misses():
    _, summary = _summary()
    m1 = summary["by_model"]["m1"]
    assert m1["num_attempted"] == 5 and m1["num_model_outputs"] == 3  # timeout and 429 are not model outputs
    assert m1["primary_fields"]["type"]["accuracy_pct"] == pytest.approx(33.3)  # 1 of scored/contract/parse
    assert m1["primary_fields"]["start_timestamp"]["mean_abs_error_s"] == 2.0  # only where both sides exist
    assert m1["primary_fields"]["start_timestamp"]["mae_n"] == 1
    assert m1["primary_fields"]["description"]["mean_judge_score"] == pytest.approx(0.8 / 3)
    assert m1["rate_limit"] == {"retries": 3, "rows_with_429": 2, "wait_s": 180.0}
    assert m1["outcomes"]["rate_limited"] == 1 and m1["outcomes"]["timeout"] == 1
    assert set(m1["primary_fields"]) == {"type", "severity_level", "start_timestamp", "end_timestamp", "description"}
    assert "duration" in m1["derived_diagnostics"]
    assert not any("overall" in key or "blended" in key for key in m1)


def test_processing_time_covers_completed_calls_only():
    _, summary = _summary()
    m1 = summary["by_model"]["m1"]
    assert m1["processing_time_s"]["n"] == 3 and m1["processing_time_s"]["mean"] == 15.0  # every completed call
    assert m1["processing_time_s"]["median"] == 15.0 and m1["processing_time_s"]["p90"] == pytest.approx(19.0)
    assert m1["failed_call_time_s"]["n"] == 2 and m1["failed_call_time_s"]["mean"] == pytest.approx(153.5)
    assert summary["by_model"]["m2"]["processing_time_s"]["mean"] == 6.0


def test_dataset_counts_each_video_once():
    _, summary = _summary()
    assert summary["dataset"]["num_videos"] == 6
    assert summary["dataset"]["size_mb"]["mean"] == pytest.approx((3 * 5 + 1) / 6)


def test_outputs_are_written(tmp_path):
    rows, summary = _summary()
    paths = export.write_outputs(rows, summary, tmp_path)
    assert {p.name for p in paths} == {
        "benchmark_per_video.csv", "benchmark_by_model.csv", "benchmark_by_category_and_model.csv",
        "benchmark_by_model.json", "benchmark_by_model.md",
    }
    with (tmp_path / "benchmark_per_video.csv").open() as handle:
        per_video = list(csv.DictReader(handle))
    assert len(per_video) == 10 and list(per_video[0]) == export.PER_VIDEO_COLUMNS
    assert json.loads((tmp_path / "benchmark_by_model.json").read_text())["by_model"]["m2"]["num_attempted"] == 3
    md = (tmp_path / "benchmark_by_model.md").read_text()
    assert "no blended score" in md and "derived" in md and "24 frames" in md  # inference.json caveat


def test_newest_run_dir(tmp_path):
    for name in ("2026-10-01T10-00-00+00-00", "2026-10-02T09-00-00+00-00"):
        (tmp_path / "runs" / name).mkdir(parents=True)
    assert export.newest_run_dir(tmp_path).name == "2026-10-02T09-00-00+00-00"
