# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""The C2-versus-C3 object audit: pure helpers, replay of chart and slide cells from raw rows, no text in repo files."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts" / "v2_c2_c3_object_audit.py"
spec = importlib.util.spec_from_file_location("objaudit", path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

TEXT_COLUMNS = {"prediction", "ground_truth", "description", "name", "predicted", "expected", "text", "note", "gt_text",
                "pred_text", "gt_object", "other_gt_same_kind"}
needs_data = pytest.mark.skipif(not audit.R.exists(), reason="private run data not present")


def block(matrix, outcome="scored", clip="Animal001", repeat=1, subject="nano-direct", kind="assets", n_gt=None):
    n_pred = len(matrix)
    return {"matrix": matrix if matrix else None, "n_pred": n_pred, "outcome": outcome, "clip": clip, "repeat": repeat,
            "n_gt": n_gt if n_gt is not None else (len(matrix[0]) if matrix else 0), "unavailable": False,
            "subject": subject, "kind": kind}


@pytest.fixture(scope="module")
def data():
    rows = {h: audit.load_half(h) for h in audit.HALVES}
    return {h: rows[h][0] for h in rows}, {h: rows[h][1] for h in rows}


def test_constants_stay_on_the_frozen_rules_and_never_name_a5s():
    import methodology

    assert methodology.MATCH_THRESHOLD == audit.sens.FROZEN == 0.40
    assert audit.RESAMPLES <= 2000
    assert all(audit.sens.FORBIDDEN_RUN not in runs for runs in audit.HALVES.values())


def test_a_rejected_row_counts_as_misses_only_in_the_invalid_as_miss_view():
    good = block([[0.9]], n_gt=1)
    rejected = block([], outcome="contract_invalid", repeat=2, n_gt=3)
    blocks = [good, rejected]
    assert audit.pool(audit.select(blocks, "nano-direct", "assets", "valid")) == (1, 0, 0)
    assert audit.pool(audit.select(blocks, "nano-direct", "assets", "outputs")) == (1, 0, 3)


def test_a_row_without_model_output_is_in_neither_view_but_is_a_miss_end_to_end():
    blocks = [block([[0.9]], n_gt=1), block([], outcome="http_error", repeat=2, n_gt=3)]
    chosen = audit.select(blocks, "nano-direct", "assets", "outputs")
    assert audit.pool(chosen) == (1, 0, 0)
    assert audit.planned_counts(chosen, 3) == (1, 0, 3)


def test_micro_pools_before_f1_and_macro_averages_clips():
    blocks = [block([[0.9]], clip="A1"), block([[0.9], [0.1], [0.1], [0.1]], clip="B2")]
    assert audit.f1(*audit.pool(blocks)) == pytest.approx(4 / 7)
    assert audit.macro_f1(blocks) == pytest.approx((1 + 0.4) / 2)


def test_empty_slice_is_not_scored_as_zero():
    assert audit.f1_of([]) is None


def test_reweighting_to_the_same_mix_returns_the_pooled_f1():
    blocks = [block([[0.9]], clip="Animal001"), block([[0.1]], clip="Burglary001")]
    assert audit.reweighted_f1(blocks, audit.row_mix(blocks)) == pytest.approx(audit.f1(*audit.pool(blocks)))


def test_reweighting_moves_toward_the_heavier_category():
    blocks = [block([[0.9]], clip="Animal001"), block([[0.1]], clip="Burglary001")]
    assert audit.reweighted_f1(blocks, {"Animal": 9, "Burglary": 1}) > audit.f1(*audit.pool(blocks))


def test_swap_effects_change_one_side_only():
    swap = audit.swap_effects((5, 5, 5), (5, 15, 5))
    assert swap["f1_c3_recall_only"] == pytest.approx(0.5)
    assert swap["f1_c3_precision_only"] < 0.5


def test_dropping_the_top_row_removes_exactly_one_row():
    rows = [block([[0.9]], clip="A1"), block([[0.1], [0.1], [0.1]], clip="B2")]
    assert [b["clip"] for b in audit.drop_top_fp_row(rows)] == ["A1"]


def test_the_preregistration_still_defines_the_two_object_views():
    text = (audit.EVAL / "methodology" / "evaluation-v2-preregistration.md").read_text(encoding="utf-8")
    assert "(conditional) | valid outputs (pooled items)" in text
    assert "an invalid or missing output contributes every ground-truth item as missed" in text


@needs_data
def test_replay_reproduces_every_chart_cell_and_stored_count(data):
    _, blocks = data
    checks = audit.replay_checks(blocks)
    for half in audit.HALVES:
        assert checks[half]["count_mismatches"] == 0
        assert checks[half]["chart_cells"] == 15 and checks[half]["chart_cell_mismatches"] == 0
        assert checks[half]["sweep_cells"] == 120 and checks[half]["sweep_cell_mismatches"] == 0
        assert checks[half]["invalid_blocks_with_predictions"] == 0
        assert checks[half]["lowest_stored_similarity"] >= 0.40


@needs_data
def test_every_slide_value_is_dev_valid_only_at_three_decimals(data):
    _, blocks = data
    for subject, (asset, instrument) in audit.SLIDE.items():
        assert round(audit.f1(*audit.pool(audit.select(blocks["dev"], subject, "assets", "valid"))), 3) == asset
        assert round(audit.f1(*audit.pool(audit.select(blocks["dev"], subject, "instruments", "valid"))), 3) == instrument


@needs_data
def test_c3_claims_are_the_invalid_as_miss_view_and_super_asset_is_a_double_rounding(data):
    _, blocks = data
    for subject, (asset, instrument) in audit.C3_CLAIM.items():
        got = [audit.f1(*audit.pool(audit.select(blocks["evaluation"], subject, k, "outputs"))) for k in audit.FOCUS]
        assert got[0] == pytest.approx(asset, abs=0.00051) and got[1] == pytest.approx(instrument, abs=0.00051)
    exact = audit.f1(*audit.pool(audit.select(blocks["evaluation"], "super-direct", "assets", "outputs")))
    assert round(exact, 3) == 0.216 and round(exact, 4) == 0.2165


@needs_data
def test_the_slide_is_not_a_macro_or_a_075_figure(data):
    _, blocks = data
    gemma = audit.select(blocks["dev"], "gemma4-31b-openrouter", "assets", "valid")
    assert round(audit.macro_f1(gemma), 3) != 0.704
    assert round(audit.f1(*audit.pool(gemma, 0.75)), 3) != 0.704


@needs_data
def test_the_two_halves_share_no_clip_and_keep_their_sizes():
    ids = audit.split_ids()
    assert (len(ids["dev"]), len(ids["evaluation"])) == (25, 55)
    assert not set(ids["dev"]) & set(ids["evaluation"])


@needs_data
def test_c3_final_analysis_holds_the_conditional_counts_the_chart_leaves_out(data):
    _, blocks = data
    final = json.loads((audit.DATA / "results-final" / "c3-final-analysis.json").read_text())
    gemma = final["original_track_a"]["summaries"]["gemma4-31b-openrouter"]
    tp, fp, fn = audit.pool(audit.select(blocks["evaluation"], "gemma4-31b-openrouter", "assets", "valid"))
    assert gemma["assets_cond_precision"]["denominator"] == tp + fp
    assert gemma["assets_cond_recall"]["denominator"] == tp + fn


def test_repo_csvs_hold_no_text_columns():
    files = list(audit.OUT.glob("*.csv"))
    assert len(files) >= 14
    for file in files:
        with file.open(encoding="utf-8") as handle:
            columns = set(next(csv.reader(handle)))
        assert not columns & TEXT_COLUMNS, file.name


def test_examples_index_uses_only_the_named_classes_and_short_cells():
    rows = audit.read_csv(audit.OUT / "examples_index.csv")
    assert rows and {r["class"] for r in rows} <= set(audit.CLASSES)
    assert all(len(v) < 40 for r in rows for v in r.values())


@needs_data
def test_no_ground_truth_or_prediction_text_reaches_the_repo_files(data):
    rows, _ = data
    texts = set()
    for half in rows.values():
        for r in half.values():
            for side in ("ground_truth", "prediction"):
                for kind in audit.KINDS:
                    texts |= {x.get("description") for x in (r.get(side) or {}).get(kind) or [] if len(x.get("description") or "") > 24}
    files = [*audit.OUT.glob("*.csv"), *audit.OUT.glob("*.md"), *audit.OUT.glob("*.json")]
    assert files
    for file in files:
        body = file.read_text(encoding="utf-8")
        assert not [t for t in texts if t in body], file.name
