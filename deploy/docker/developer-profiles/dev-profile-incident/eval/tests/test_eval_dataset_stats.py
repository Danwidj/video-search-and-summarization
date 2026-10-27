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

"""eval_dataset_stats: per-video size/length rows and summary statistics - no R2 access."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_dataset_stats  # noqa: E402
from eval_dataset_stats import collect, summarize, summary_stats  # noqa: E402
from eval_video_resolution import build_basename_index  # noqa: E402

MANIFESTS = [
    {"category": "Assault", "evaluation_videos": ["A1.mp4", "A2.mp4"],
     "evaluation_videos_r2_keys": {"A1.mp4": "anomaly/assault/A1.mp4", "A2.mp4": "anomaly/assault/A2.mp4"}},
    {"category": "Burglary", "evaluation_videos": ["B1.mp4", "Gone.mp4", "Moved.mp4"],
     "evaluation_videos_r2_keys": {"B1.mp4": "anomaly/burglary/B1.mp4", "Gone.mp4": "anomaly/burglary/Gone.mp4",
                                   "Moved.mp4": "anomaly/burglary/Moved.mp4"}},
]
KEYS = ["anomaly/assault/A1.mp4", "anomaly/assault/A2.mp4", "anomaly/burglary/B1.mp4", "elsewhere/Moved.mp4"]
METADATA = {
    "anomaly/assault/A1.mp4": {"size_bytes": 2_000_000, "duration_seconds": 10.0},
    "anomaly/assault/A2.mp4": {"size_bytes": 4_000_000, "duration_seconds": None},
    "anomaly/burglary/B1.mp4": {"size_bytes": 6_000_000, "duration_seconds": 30.0},
}


def _rows():
    return collect(MANIFESTS, build_basename_index(KEYS), METADATA.__getitem__)


def test_every_manifest_video_has_a_row_and_failures_are_explained():
    rows = {r["filename"]: r for r in _rows()}
    assert list(rows) == ["A1.mp4", "A2.mp4", "B1.mp4", "Gone.mp4", "Moved.mp4"]
    assert rows["A1.mp4"]["size_mb"] == pytest.approx(2.0) and rows["A1.mp4"]["error"] == ""
    assert rows["A2.mp4"]["duration_seconds"] is None and "length unreadable" in rows["A2.mp4"]["error"]
    assert "no R2 object" in rows["Gone.mp4"]["error"] and rows["Gone.mp4"]["size_bytes"] is None
    assert "differs from manifest" in rows["Moved.mp4"]["error"]


def test_summary_averages_known_values_and_counts_unknowns():
    summary = summarize(_rows())
    overall = summary["overall"]
    assert overall["num_videos"] == 5 and overall["num_unresolved"] == 2
    assert overall["duration_seconds"]["mean"] == pytest.approx(20.0)
    assert overall["duration_seconds"]["n"] == 2 and overall["duration_seconds"]["unknown"] == 3
    assert overall["size_mb"]["mean"] == pytest.approx(4.0) and overall["size_mb"]["total"] == pytest.approx(12.0)
    assert summary["by_category"]["Assault"]["size_mb"]["mean"] == pytest.approx(3.0)


def test_summary_stats_median_p90_and_edge_cases():
    stats = summary_stats([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, None])
    assert stats["median"] == 5.5 and stats["p90"] == pytest.approx(9.1) and stats["unknown"] == 1
    assert summary_stats([4.0])["p90"] == 4.0
    assert summary_stats([None])["mean"] is None and summary_stats([])["n"] == 0


def test_write_outputs(tmp_path):
    json_path, csv_path = eval_dataset_stats.write_outputs(_rows(), results_dir=tmp_path)
    data = json.loads(json_path.read_text())
    assert len(data["videos"]) == 5 and data["summary"]["overall"]["size_mb"]["n"] == 3
    assert csv_path.read_text().splitlines()[0].split(",") == eval_dataset_stats.CSV_COLUMNS


def test_missing_manifests_are_reported(tmp_path):
    with pytest.raises(FileNotFoundError, match="eval_reproducibility"):
        eval_dataset_stats.load_manifests(tmp_path)
