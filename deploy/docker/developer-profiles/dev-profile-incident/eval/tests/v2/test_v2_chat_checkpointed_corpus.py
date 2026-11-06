# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""C3 amendment A4: a system corpus may add named, already-answered items from a Track B run's checkpoint."""

import json

import pytest

from evalv2.core.artifacts import ArtifactStore
from evalv2.tasks.chat import corpus


def _run(tmp_path):
    run = tmp_path / "run"; store = ArtifactStore(run / "store")
    ref = store.put("pipeline-prediction", {"stages": {"final": {"incident": {"type": "burglary"}}}})
    rows = [{"subject": "super-pipeline", "item_id": "Burglary041", "repeat": 1, "outcome": "scored", "prediction_ref": str(ref), "ref": "x"},
            {"subject": "super-pipeline", "item_id": "Burglary052", "repeat": 1, "outcome": "http_error", "prediction_ref": None, "ref": "y"}]
    (run / "checkpoint.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return run


def test_a_checkpointed_prediction_is_loaded(tmp_path):
    got = corpus.load_checkpointed_predictions(_run(tmp_path), "super-pipeline", ["Burglary041"])
    assert got["Burglary041"]["stages"]["final"]["incident"]["type"] == "burglary"


def test_an_item_without_a_prediction_or_not_in_the_checkpoint_is_refused(tmp_path):
    run = _run(tmp_path)
    with pytest.raises(corpus.CorpusError, match="no prediction"):
        corpus.load_checkpointed_predictions(run, "super-pipeline", ["Burglary052"])
    with pytest.raises(corpus.CorpusError, match="not in the checkpoint"):
        corpus.load_checkpointed_predictions(run, "super-pipeline", ["Assault001"])
