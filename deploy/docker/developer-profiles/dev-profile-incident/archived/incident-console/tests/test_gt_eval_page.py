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

"""Tier 1 GT evaluation exercised through the real report-detail page.

Complements ``test_eval_gt.py`` (unit-level ``run_evaluation``) by driving the
actual "Run GT Evaluation" button on ``pages/2_Report_Review.py`` end to end
against the hermetic SQLite fixture - the same way a reviewer would click
through the console.
"""

from __future__ import annotations

import datetime
import re
from collections import Counter
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import embed_client
import eval_gt
import matching
from scripts.seed_gt_demo import seed as seed_gt_demo


def _fake_embed(texts):
    tokenized = [re.findall(r"[a-z']+", text.lower()) for text in texts]
    vocab = sorted({word for tokens in tokenized for word in tokens})
    vectors = [[float(Counter(tokens).get(word, 0)) for word in vocab] for tokens in tokenized]
    return embed_client.Result(ok=True, data=vectors)


@pytest.fixture
def gt_eval_page(incident_db, monkeypatch):
    seed_gt_demo(incident_db)
    monkeypatch.setattr("config.incident_db_dsn", lambda: str(incident_db.engine.url))
    monkeypatch.setattr("db.is_configured", lambda: True)
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    monkeypatch.setattr(matching, "embed_texts", _fake_embed)
    return incident_db


def test_gt_evaluation_button_renders_field_and_match_results(gt_eval_page):
    """Burglary001 is the demo's all-pass scenario: reworded-but-equivalent
    description, an in-tolerance start timestamp, and matching severity/type.
    """
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = "Burglary001"
    with patch.object(eval_gt, "judge_description_similarity", return_value=eval_gt.Result(ok=True, data=0.9)):
        app.run()
        assert not app.exception
        run_button = next(b for b in app.button if b.label == "Run GT Evaluation")
        run_button.click().run()
    assert not app.exception

    assert any("Ground-truth evaluation" in m.value for m in app.markdown)
    # Type/severity/start-timestamp all pass for this scenario; the
    # description judge score (0.9) is rendered as its own pill.
    assert any("Pass" in m.value for m in app.markdown)
    assert any("0.90" in m.value for m in app.markdown)

    # Evidence matching renders TP/FP/FN/P/R/F1 metrics per matching category.
    labels = {m.label for m in app.metric}
    assert labels == {"TP", "FP", "FN", "Precision", "Recall", "F1"}


def test_gt_evaluation_flags_out_of_tolerance_timestamp(gt_eval_page):
    """Burglary002 shifts the model's start timestamp well outside tolerance."""
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = "Burglary002"
    with patch.object(eval_gt, "judge_description_similarity", return_value=eval_gt.Result(ok=True, data=0.9)):
        app.run()
        next(b for b in app.button if b.label == "Run GT Evaluation").click().run()
    assert not app.exception
    assert any("Fail" in m.value for m in app.markdown)


def test_gt_evaluation_result_is_not_stale_after_a_new_model_run(gt_eval_page):
    """Regression for the reviewed stale-cache-key fix.

    The cached evaluation result used to be keyed only by incident id. If a
    user runs GT evaluation, a *new* model run then lands for the same
    incident (re-analysis), and the user revisits the same report-detail page
    in the same session, the page must not keep showing the old model run's
    cached evaluation next to the new model run's fields.
    """
    incident_id = "Burglary001"
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = incident_id
    with patch.object(eval_gt, "judge_description_similarity", return_value=eval_gt.Result(ok=True, data=0.9)):
        app.run()
        next(b for b in app.button if b.label == "Run GT Evaluation").click().run()
    assert any("Incident fields" in c.value for c in app.caption)

    # Simulate re-analysis: a brand-new model run supersedes the one just evaluated.
    gt_eval_page.insert_model_run(
        "MR-RERUN",
        model_name="incident-vlm-v2",
        run_datetime=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1),
    )
    gt_eval_page.insert_incident(
        incident_id,
        "MR-RERUN",
        fields={
            "type": "burglary",
            "severity_level": 2,
            "start_timestamp": "00:00:08",
            "end_timestamp": "00:01:57",
            "duration": 109,
            "description": "a completely different unevaluated re-analysis output",
        },
    )

    # Revisit the same page/session without clicking "Run GT Evaluation" again.
    app.run()
    assert not app.exception
    assert any(b.label == "Run GT Evaluation" for b in app.button)
    # No leftover evaluation output for the new, unevaluated model run.
    assert not any("Incident fields" in c.value for c in app.caption)
    assert len(app.metric) == 0
