"""Video mapping stays session-local; incident data never requires R2."""

from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from fixtures.dashboard_seed import load_seed
from local_reports import LocalReports


def test_same_seed_and_isolated_edits():
    handle = LocalReports({})
    seed = load_seed()["Incident"]
    assert len(handle.list_reports()) == len(seed) == 72
    first_id = seed[0]["Incident_ID"]
    assert handle.get_report(first_id)["description"] == seed[0]["Description"]
    handle.update_report(first_id, fields={"description": ""}, edited_by="Reviewer")
    assert load_seed()["Incident"][0]["Description"] == seed[0]["Description"]


def test_player_uses_explicit_url_and_seed_timestamp():
    app = AppTest.from_file("../pages/2_Report_Review.py")
    app.query_params["report"] = "Burglary001"  # real ground-truth incident: 00:00:08 -> 00:01:57
    app.run()
    url = "https://media.example.invalid/clip.mp4?token=opaque"
    next(t for t in app.text_input if t.label == "Video playback URL").set_value(url)
    next(b for b in app.button if b.label == "Use this video").click().run()
    assert not app.exception
    assert app.get("video")[0].proto.start_time == 8
    assert app.get("video")[0].proto.url == url
    next(b for b in app.button if b.label == "Jump to incident end").click().run()
    assert not app.exception
    assert app.get("video")[0].proto.start_time == 117


def test_two_page_entrypoint():
    with patch("streamlit.navigation", wraps=st.navigation) as navigation:
        app = AppTest.from_file("../app.py", default_timeout=10).run()
        assert not app.exception
        assert [page.title for page in navigation.call_args.args[0]] == ["Incident Reports", "Analytics Dashboard"]
