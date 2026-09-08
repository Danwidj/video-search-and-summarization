"""Detail-view tests use existing canned test content, never UI seed data."""

import pytest
from streamlit.testing.v1 import AppTest

from incident_report import canned_incident_report
from report_detail import confidence_label, normalized, seconds


def test_missing_values_and_strict_times():
    assert all(value is None for value in normalized({}).values())
    assert seconds(0) == 0
    assert seconds("1:02:03") == 3723
    assert seconds("1:99") is None
    assert seconds(-1) is None
    assert confidence_label(None) == "Not supplied"
    assert confidence_label(0) == "0.0%"
    assert "invalid" in confidence_label(float("nan"))
    fields = normalized(canned_incident_report().model_dump())
    assert fields["Duration"] == 22
    assert normalized({"Start_Timestamp": 9, "End_Timestamp": 2})["Duration"] is None


def test_review_transitions(incident_db):
    rid = incident_db.insert_report(video_id=None, report=canned_incident_report("robbery").model_dump())
    for status in ("under review", "verified", "verified", "unreviewed"):
        incident_db.set_report_review_status(rid, status=status, reviewed_by="Reviewer", notify_threshold=4)
        assert incident_db.get_report(rid)["status"] == status
    assert len(incident_db.list_notifications()) == 1
    row = incident_db.get_report(rid)
    assert row["verified_by"] is None
    assert row["verified_at"] is None
    assert row["edited_by"] == "Reviewer"
    assert row["edited_at"] is not None
    with pytest.raises(ValueError):
        incident_db.set_report_review_status(rid, status="invalid", reviewed_by="Reviewer", notify_threshold=4)
    with pytest.raises(ValueError):
        incident_db.set_report_review_status(9999, status="verified", reviewed_by="Reviewer", notify_threshold=4)


def test_detail_navigation_edit_and_status():
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=10).run()
    assert not app.exception
    assert len([b for b in app.button if b.label == "View and Verify Details"]) == 72
    next(b for b in app.button if b.label == "View and Verify Details").click().run()
    assert not app.exception
    assert app.query_params["report"] == ["Burglary001"]
    assert any("AI summary not yet generated" in i.value for i in app.info)
    app.toggle[0].set_value(True).run()
    next(t for t in app.text_input if t.label == "Edited by").set_value("Reviewer")
    next(b for b in app.button if b.label == "Save changes").click().run()
    assert not app.exception
    assert app.session_state["local_incident_reports"]["Burglary001"]["confidence"] is None
    assert app.toggle[0].value is False
    next(s for s in app.selectbox if s.label == "Review status").set_value("under review")
    next(t for t in app.text_input if t.label == "Reviewed by").set_value("Reviewer")
    next(b for b in app.button if b.label == "Save review status").click().run()
    assert not app.exception
    assert app.session_state["local_incident_reports"]["Burglary001"]["status"] == "under review"
    next(b for b in app.button if b.label == "← Back to Incident Reports").click().run()
    assert not app.exception
    assert "report" not in app.query_params


def test_missing_record():
    app = AppTest.from_file("../pages/2_Report_Review.py")
    app.query_params["report"] = "missing"
    app.run()
    assert not app.exception
    assert any("was not found" in i.value for i in app.info)


def test_inline_edit_cancel_discards_draft():
    app = AppTest.from_file("../pages/2_Report_Review.py", default_timeout=10)
    app.query_params["report"] = "Burglary001"
    app.run()
    original = app.session_state["local_incident_reports"]["Burglary001"]["description"]
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert len(app.text_area) == 1
    # The read-only description is replaced, not repeated beside an edit form.
    assert not any(t.value == original for t in app.text)
    app.text_area[0].set_value("Unsaved reviewer draft")
    next(b for b in app.button if b.label == "Cancel").click().run()
    assert not app.exception
    assert app.toggle[0].value is False
    assert app.session_state["local_incident_reports"]["Burglary001"]["description"] == original
    app.toggle[0].set_value(True).run()
    assert app.text_area[0].value == original
