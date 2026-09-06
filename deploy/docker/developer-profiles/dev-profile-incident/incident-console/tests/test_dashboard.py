"""Fixture integrity and dashboard interactions without a database."""

from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from dashboard_view import frame, review_queue
from fixtures.dashboard_seed import load_seed


def test_seed_relationships_and_queue():
    seed = load_seed()
    incidents = {r["Incident_ID"]: r for r in seed["Incident"]}
    assert len(incidents) == 18
    for row in incidents.values():
        assert row["Type"] in {"animal", "road accident", "burglary", "explosion", "fighting"}
        assert 1 <= row["Severity"] <= 5
        assert (pd.to_timedelta(row["End_Timestamp"]) - pd.to_timedelta(row["Start_Timestamp"])).total_seconds() == row[
            "Duration"
        ]
    for name in ("Entity", "Instrument", "Asset"):
        for row in seed[name]:
            assert row["Incident_ID"] in incidents
            assert row["Filename"] == incidents[row["Incident_ID"]]["Filename"]
    for row in seed["Instrument"]:
        assert any(e["Incident_ID"] == row["Incident_ID"] and e["ID"] == row["Entity_ID"] for e in seed["Entity"])
    for incident_id in incidents:
        assert 1 <= sum(e["Incident_ID"] == incident_id for e in seed["Entity"]) <= 3
    queue = review_queue(frame(seed["Incident"]))
    assert queue.iloc[0].Confidence_Score != queue.iloc[0].Confidence_Score
    scores = queue.Confidence_Score.dropna().tolist()
    assert scores == sorted(scores)
    assert all(score < 0.7 for score in scores)


def test_dashboard_preview_filters_reset_and_empty():
    with patch("db.is_configured", return_value=False):
        app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=15).run()
        assert not app.exception
        assert app.metric[0].value == "18"
        app.multiselect[0].set_value(["explosion"]).run()
        assert not app.exception
        assert app.metric[0].value == "2"
        app.multiselect[1].set_value(["bag"]).run()
        assert not app.exception
        assert app.metric[0].value == "0"
        app.button[0].click().run()
        assert app.metric[0].value == "18"
        app.toggle[0].set_value(False).run()
        assert not app.exception
        assert app.metric[0].value == "0"
