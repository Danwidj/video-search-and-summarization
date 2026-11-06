# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The exploratory object-threshold analysis: replay at 0.40, grid, no text in repo files, selection before evaluation."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts" / "v2_object_threshold_sensitivity.py"
spec = importlib.util.spec_from_file_location("objsens", path)
sens = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sens)

TEXT_COLUMNS = {"prediction", "ground_truth", "description", "name", "predicted", "expected", "text", "note", "other_gt_same_kind"}


def block(matrix, n_pred=None, n_gt=None):
    return {"matrix": matrix, "n_pred": n_pred if n_pred is not None else len(matrix),
            "n_gt": n_gt if n_gt is not None else len(matrix[0]), "unavailable": False}


def test_grid_holds_the_requested_values_and_the_frozen_threshold():
    assert sens.THRESHOLDS == (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60)
    assert sens.FROZEN == 0.40 and sens.FROZEN in sens.THRESHOLDS


def test_frozen_threshold_matches_the_pinned_methodology():
    import methodology

    assert methodology.MATCH_THRESHOLD == sens.FROZEN and methodology.EMBEDDING_MODEL == sens.EMBEDDER
    assert methodology.BOOTSTRAP_SEED == sens.SEED
    assert sens.RESAMPLES <= 2000


def test_boundary_is_inclusive_like_the_matcher():
    assert sens.counts(block([[0.40]]), 0.40) == (1, 0, 0)
    assert sens.counts(block([[0.3999]]), 0.40) == (0, 1, 1)


def test_lowering_the_threshold_cannot_lower_measured_f1():
    """The reason measured F1 cannot pick a threshold: assignment comes first, so wrong pairs also raise it."""
    b = block([[0.9, 0.31, 0.2], [0.33, 0.25, 0.1], [0.1, 0.21, 0.36]])
    scores = [sens.f1(*sens.counts(b, t)) for t in sorted(sens.THRESHOLDS)]
    assert scores == sorted(scores, reverse=True)


def test_assign_then_filter_can_lose_a_match_that_filter_first_keeps():
    matrix = [[0.45, 0.39], [0.39, 0.00]]
    assert sens.counts(block(matrix), 0.40)[0] == 0  # the sum 0.78 beats 0.45, then both pairs fall below 0.40
    assert len(sens.threshold_first(matrix, 0.40)) == 1


def test_object_score_is_the_chart_formula():
    entity, instrument, asset = (1, 1, 0), (1, 0, 1), (2, 2, 2)
    assert sens.object_score(entity, instrument, asset) == pytest.approx((2 / 3 + sens.f1(3, 2, 3)) / 2)


def test_a5s_output_is_refused():
    with pytest.raises(ValueError):
        sens.load_rows((sens.FORBIDDEN_RUN,))
    assert sens.FORBIDDEN_RUN not in sens.EVAL_RUNS + sens.DEV_RUNS


def test_sample_is_seeded_quota_bound_and_fills_each_band():
    pairs = [{"subject": s, "clip": f"Assault{i:03d}", "repeat": 1, "kind": k, "model_id": f"E{i}", "gt_id": "E1",
              "similarity": 0.205 + 0.0098 * i} for s in sens.MODELS for k in sens.KINDS for i in range(30)]
    first, second = sens.draw_sample(pairs), sens.draw_sample(pairs)
    assert [p["sample_id"] for p in first] == [p["sample_id"] for p in second]
    assert [p["similarity"] for p in first] == [p["similarity"] for p in second]
    for lo, hi, quota in sens.BANDS:
        assert sum(p["band"] == f"{lo:.2f}-{hi:.2f}" for p in first) == quota


def test_weighted_precision_counts_cannot_tell_against_unless_asked():
    labelled = [{"band": "0.35-0.40", "kind": "entities", "subject": "nano-direct", "clip": "A", "label": v}
                for v in ("same", "different", "cannot_tell", "same")]
    cells = {("0.35-0.40", "entities", "nano-direct"): 10}
    assert sens.weighted_precision(labelled, cells) == 0.5
    assert sens.weighted_precision(labelled, cells, exclude_cannot_tell=True) == pytest.approx(2 / 3)


data = pytest.mark.skipif(not (sens.R / "c1a" / sens.SCORE).exists(), reason="stored runs are local only")


@data
@pytest.mark.parametrize("runs", [sens.DEV_RUNS, sens.EVAL_RUNS], ids=["dev", "evaluation"])
def test_replay_reproduces_every_stored_count_at_040(runs):
    _, blocks, audit = sens.load_half(runs)
    check = sens.replay_check(blocks)
    assert check.get("count_mismatches", 0) == 0 and check["blocks_compared"] > 700
    assert not audit.get("blocks_missing_a_vector")


def test_repo_csvs_hold_no_text_columns():
    files = list(sens.OUT.glob("*.csv"))
    assert files
    for file in files:
        with file.open() as handle:
            columns = set(next(csv.reader(handle)))
        assert not columns & TEXT_COLUMNS, file.name


def test_labelled_pairs_csv_holds_ids_and_codes_only():
    rows = sens.read_csv(sens.OUT / "dev_labelled_pairs.csv")
    assert len(rows) == 140 and {r["label"] for r in rows} <= set(sens.LABELS) and {r["mode"] for r in rows} <= set(sens.MODES)
    assert all(len(v) < 40 for r in rows for v in r.values())


def test_selection_was_sealed_before_the_evaluation_sweep():
    ledger = json.loads(sens.LEDGER.read_text())
    assert sens.selection_sealed()
    assert ledger["dev_gates_sha256"] == sens.sha256(sens.OUT / "dev_gates.csv")
    for name in ("evaluation_object_score.csv", "evaluation_sweep_by_kind.csv"):
        assert (sens.OUT / name).stat().st_mtime >= sens.LEDGER.stat().st_mtime
    assert sens.sha256(sens.RULE) in sens.SELECTION.read_text()


def test_evaluation_sweep_refuses_without_a_seal(monkeypatch, tmp_path):
    monkeypatch.setattr(sens, "LEDGER", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        sens.cmd_evaluation()


def test_no_lower_threshold_passed_the_gates():
    gates = sens.read_csv(sens.OUT / "dev_gates.csv")
    assert {g["all_pass"] for g in gates} == {"False"}
