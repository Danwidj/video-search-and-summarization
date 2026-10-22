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

"""Report Review and Dashboard render from the database when a DSN is configured.

The database is the hermetic SQLite fixture; R2 stays stubbed unconfigured.
"""

from __future__ import annotations

import json
import re

import pytest
from streamlit.testing.v1 import AppTest

from scripts.seed_supabase import seed


@pytest.fixture
def db_pages(incident_db, monkeypatch):
    seed(incident_db)
    monkeypatch.setattr("config.incident_db_dsn", lambda: str(incident_db.engine.url))
    monkeypatch.setattr("db.is_configured", lambda: True)
    monkeypatch.setattr("db.get_db", lambda: incident_db)
    return incident_db


@pytest.fixture
def playable_pages(db_pages, monkeypatch):
    """``db_pages`` plus a media base URL, so every incident *could* render a clip preview."""
    monkeypatch.setattr("config.video_base_url", lambda: "https://media.example.com")
    return db_pages


def _first_incident_id(database) -> str:
    return sorted(r["incident_id"] for r in database.list_latest_incidents())[0]


def _load_preview_buttons(app):
    return [b for b in app.button if b.label == "Load preview"]


def _count_calls(monkeypatch, database, method: str) -> list:
    """Wrap ``database.<method>`` so each call's arguments are appended to the returned list."""
    calls: list = []
    real = getattr(database, method)

    def wrapper(*args, **kwargs):
        calls.append(args or kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(database, method, wrapper)
    return calls


def test_report_review_lists_the_36_from_the_db(db_pages):
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    assert not app.exception
    assert len([b for b in app.button if b.label == "View and Verify Details"]) == 36


def test_report_review_detail_has_db_controls_and_seek(db_pages):
    rid = sorted(r["incident_id"] for r in db_pages.list_latest_incidents())[0]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = rid
    app.run()
    assert not app.exception
    # DB-only controls are present.
    assert any(b.label == "Save review status" for b in app.button)
    assert any("Link source video from Cloudflare R2" in m.value for m in app.markdown)
    # Jump-to-start uses the stored incident start (auto-seek path).
    assert any("Jump to incident start" in b.label for b in app.button)


def test_report_review_edit_persists_across_a_rerun(db_pages):
    rid = sorted(r["incident_id"] for r in db_pages.list_latest_incidents())[0]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = rid
    app.run()
    app.toggle[0].set_value(True).run()
    app.text_area[0].set_value("persisted through the database")
    next(b for b in app.button if b.label == "Save changes").click().run()
    assert not app.exception
    reloaded = db_pages.get_latest_incident(rid)
    assert reloaded["description"] == "persisted through the database"


def test_report_review_card_preview_does_not_use_deprecated_components_html(playable_pages):
    """Regression: the incident-card video preview used to call the deprecated
    ``st.components.v1.html`` once per card, spamming the log on every list
    render. It must render through ``st.iframe`` instead, with no deprecation
    warning logged. Previews are lazy now, so one is requested first to make the
    ``st.iframe`` path actually run.

    ``streamlit.deprecation_util``'s logger has ``propagate=False``, so
    pytest's ``caplog`` (which listens on the root logger) can't see its
    records; a handler must be attached to it directly.
    """
    import logging

    rid = _first_incident_id(playable_pages)
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    deprecation_logger = logging.getLogger("streamlit.deprecation_util")
    deprecation_logger.addHandler(handler)
    try:
        app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
        app.button(key=f"load_preview_{rid}").click().run()
    finally:
        deprecation_logger.removeHandler(handler)
    assert not app.exception
    assert len(app.get("iframe")) == 1
    assert not any("components.v1.html" in r.getMessage() for r in records)


def test_library_renders_no_previews_until_requested(playable_pages, monkeypatch):
    """Regression: the library mounted a ``<video>`` iframe per card (36 at once), which opened
    ~4 media requests per incident (most cancelled) and one ``get_video`` database round trip
    per card. Nothing must be fetched or looked up until a preview is asked for."""
    lookups = _count_calls(monkeypatch, playable_pages, "get_latest_incident")
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    assert not app.exception
    assert app.get("iframe") == []
    assert len(_load_preview_buttons(app)) == 36
    assert lookups == []


def test_load_preview_renders_only_the_requested_incident(playable_pages, monkeypatch):
    rid = _first_incident_id(playable_pages)
    key = playable_pages.get_latest_incident(rid)["video_filepath"]
    lookups = _count_calls(monkeypatch, playable_pages, "get_latest_incident")
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    app.button(key=f"load_preview_{rid}").click().run()
    assert not app.exception
    frames = app.get("iframe")
    assert len(frames) == 1
    assert f"https://media.example.com/{key}" in frames[0].proto.srcdoc
    assert 'preload="metadata"' in frames[0].proto.srcdoc
    assert lookups == [(rid,)]
    assert len(_load_preview_buttons(app)) == 35


def test_loaded_preview_survives_a_rerun_and_a_filter_change(playable_pages):
    rows = playable_pages.list_latest_incidents()
    rid = _first_incident_id(playable_pages)
    incident_type = next(r["type"] for r in rows if r["incident_id"] == rid)
    same_type = [r for r in rows if r["type"] == incident_type]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    app.button(key=f"load_preview_{rid}").click().run()
    app.run()
    assert len(app.get("iframe")) == 1
    app.selectbox(key="review_type").set_value(incident_type).run()
    assert not app.exception
    assert len(app.get("iframe")) == 1
    assert len(_load_preview_buttons(app)) == len(same_type) - 1


def test_incident_without_a_linked_clip_offers_no_preview(playable_pages):
    rid = _first_incident_id(playable_pages)
    playable_pages.update_video(rid, filepath=None)
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    assert not app.exception
    assert len(_load_preview_buttons(app)) == 35
    assert all(b.key != f"load_preview_{rid}" for b in app.button)


def test_library_without_a_playback_source_offers_no_preview(db_pages):
    """No media base URL and no R2 keys: nothing could ever play, so cards stay a plain poster
    (as before) rather than offering a button that can only fail."""
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    assert not app.exception
    assert len([b for b in app.button if b.label == "View and Verify Details"]) == 36
    assert _load_preview_buttons(app) == []
    assert app.get("iframe") == []


def test_load_preview_for_an_unresolvable_clip_says_so(playable_pages, monkeypatch):
    """If the clip cannot be resolved when the click arrives (row re-linked or removed since the
    list rendered) the card must explain itself instead of silently doing nothing."""
    rid = _first_incident_id(playable_pages)
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    monkeypatch.setattr("db_reports.DBReports.get_video", lambda self, report_id: {})
    app.button(key=f"load_preview_{rid}").click().run()
    assert not app.exception
    assert app.get("iframe") == []
    assert any("Preview unavailable" in c.value for c in app.caption)


def test_library_default_load_lists_incidents_once(db_pages, monkeypatch):
    """With no filter active the type options and the card list come from one query, not two."""
    incident_type = db_pages.list_latest_incidents()[0]["type"]
    listings = _count_calls(monkeypatch, db_pages, "list_latest_incidents")
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    assert not app.exception
    assert len(listings) == 1
    app.selectbox(key="review_type").set_value(incident_type).run()
    assert not app.exception
    # The rerun re-reads the unfiltered options and then the filtered list.
    assert len(listings) == 1 + 2


def test_library_load_makes_no_r2_calls_and_a_preview_signs_only_its_own_clip(db_pages, monkeypatch):
    """With R2 configured the old library signed a URL for every card on each cold cache (a boto3
    client per key). Loading the library must not touch R2 at all, and a requested preview signs
    just its own object."""
    import r2_videos

    signed: list[str] = []

    class FakeR2:
        def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803 - boto3's signature
            signed.append(Params["Key"])
            return f"https://r2.example.com/{Params['Bucket']}/{Params['Key']}?X-Amz-Signature=test"

        def get_paginator(self, name):
            raise AssertionError("the library must not list the bucket")

    monkeypatch.setenv("R2_BUCKET", "clips")
    monkeypatch.setattr("db_reports.configured", lambda: True)
    monkeypatch.setattr("r2_videos.configured", lambda: True)
    monkeypatch.setattr("r2_videos.client", FakeR2)
    r2_videos.playback_url.clear()
    try:
        rid = _first_incident_id(db_pages)
        key = db_pages.get_latest_incident(rid)["video_filepath"]
        app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
        assert not app.exception
        assert signed == []
        app.button(key=f"load_preview_{rid}").click().run()
        assert not app.exception
        assert signed == [key]
        assert f"https://r2.example.com/clips/{key}?X-Amz-Signature=test" in app.get("iframe")[0].proto.srcdoc
    finally:
        r2_videos.playback_url.clear()


def test_preview_url_cannot_break_out_of_its_script_tag(playable_pages):
    """The clip URL is embedded in a same-origin iframe's <script>; an object key containing
    ``</script>`` must stay data, and the URL must still round-trip intact."""
    rid = _first_incident_id(playable_pages)
    hostile = "x</script><script>alert(1)</script>.mp4"
    playable_pages.update_video(rid, filepath=hostile)
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15).run()
    app.button(key=f"load_preview_{rid}").click().run()
    assert not app.exception
    srcdoc = app.get("iframe")[0].proto.srcdoc
    assert "</script><script>alert" not in srcdoc
    assert srcdoc.count("</script>") == 1
    embedded = re.search(r'src=("(?:[^"\\]|\\.)*");', srcdoc)
    assert embedded and json.loads(embedded.group(1)) == f"https://media.example.com/{hostile}"


def test_report_review_missing_record_shows_notice(db_pages):
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = "999999"
    app.run()
    assert not app.exception
    assert any("was not found" in i.value for i in app.info)


def test_report_review_inline_edit_cancel_discards_draft(db_pages):
    rid = sorted(r["incident_id"] for r in db_pages.list_latest_incidents())[0]
    original = db_pages.get_latest_incident(rid)["description"]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = str(rid)
    app.run()
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert len(app.text_area) == 1
    # The read-only description is replaced, not repeated beside an edit form.
    assert not any(t.value == original for t in app.text)
    app.text_area[0].set_value("Unsaved reviewer draft")
    next(b for b in app.button if b.label == "Cancel").click().run()
    assert not app.exception
    assert app.toggle[0].value is False
    app.toggle[0].set_value(True).run()
    assert app.text_area[0].value == original
    assert db_pages.get_latest_incident(rid)["description"] == original


def test_review_status_and_reviewer_survive_nav_away_and_back(db_pages):
    """Regression: after saving a review status + "Reviewed by" name, leaving the
    detail view and re-opening it must still show both. Previously the status
    reappeared (re-read from the DB every render) but the reviewer attribution
    was dropped by ``DBReports._to_view`` and never rendered, so it looked lost.
    """
    rid = sorted(r["incident_id"] for r in db_pages.list_latest_incidents())[0]
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=15)
    app.query_params["report"] = str(rid)
    app.run()

    status_box = next(s for s in app.selectbox if s.label == "Status")
    status_box.set_value("verified").run()
    next(t for t in app.text_input if t.label == "Reviewed by").set_value("dana").run()
    next(b for b in app.button if b.label == "Save review status").click().run()
    assert not app.exception

    # Leave the detail view (the in-app "← Back" clears the query param) ...
    del app.query_params["report"]
    app.run()
    # ... then re-open the same incident.
    app.query_params["report"] = str(rid)
    app.run()
    assert not app.exception

    captions = " | ".join(c.value for c in app.caption)
    assert "Current: verified" in captions
    assert "dana" in captions


def test_dashboard_renders_charts_from_db_incidents(db_pages):
    # The default severity filter (1-5) excludes rows with no severity_level at
    # all (blank in the ground-truth sheet for every transcribed burglary /
    # road-accident incident) - fewer than the full 36 seeded incidents.
    scored = sum(1 for r in db_pages.list_latest_incidents() if r["severity_level"] is not None)
    app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=15).run()
    assert not app.exception
    assert app.metric[0].value == str(scored)
    # Evidence-driven widgets have content (entity donut / threat matrix).
    assert not any("No linked entities" in i.value for i in app.info)


def test_dashboard_records_log_filename_column_is_populated(db_pages):
    app = AppTest.from_file("../pages/3_Dashboard.py", default_timeout=15).run()
    assert not app.exception
    filenames = [
        value
        for element in app.dataframe
        if "Filename" in getattr(element.value, "columns", [])
        for value in element.value["Filename"].tolist()
    ]
    assert filenames
    assert all(name for name in filenames)
    expected = {(row["video_filepath"] or "").rsplit("/", 1)[-1] for row in db_pages.list_latest_incidents()}
    assert set(filenames) <= expected
