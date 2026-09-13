"""Search-profile template tests: canned search/frames/Kibana builders."""

import json

from search_profile_mock.state import Stream
from search_profile_mock.templates import build_agent_mode_search_answer
from search_profile_mock.templates import build_frames_response
from search_profile_mock.templates import build_kibana_dashboards
from search_profile_mock.templates import build_search_results
from search_profile_mock.templates import classify_intent


def _streams() -> dict[str, Stream]:
    return {
        "sensor-aaa": Stream(stream_id="sensor-aaa", name="clip-a.mp4", filename="clip-a.mp4", bytes_total=10),
        "sensor-bbb": Stream(stream_id="sensor-bbb", name="clip-b.mp4", filename="clip-b.mp4", bytes_total=20),
    }


def test_classify_search_intent_after_base_intents():
    assert classify_intent("summarize this stream") == "report"
    assert classify_intent("list available videos") == "video_list"
    assert classify_intent("search for a red truck") == "search"
    assert classify_intent("find people near the door") == "search"
    assert classify_intent("hello there") == "generic"


def test_search_results_shape_matches_ui_contract():
    items = build_search_results(_streams(), "red truck", top_k=10)

    assert len(items) == 2
    required = {
        "video_name",
        "similarity",
        "screenshot_url",
        "description",
        "start_time",
        "end_time",
        "sensor_id",
        "object_ids",
        "critic_result",
    }
    for item in items:
        assert required <= set(item)
    assert items[0]["similarity"] >= items[1]["similarity"]


def test_search_results_respect_top_k_and_filters():
    items = build_search_results(_streams(), "query", top_k=1)
    assert len(items) == 1

    assert build_search_results(_streams(), "query", top_k=0) == []
    assert build_search_results({}, "query") == []
    assert build_search_results(_streams(), "query", video_sources=["sensor-aaa"]) != []
    only_b = build_search_results(_streams(), "query", video_sources=["sensor-bbb"])
    assert [i["sensor_id"] for i in only_b] == ["sensor-bbb"]
    assert build_search_results(_streams(), "query", min_similarity=0.9999) == []


def test_search_results_deterministic():
    import datetime as dt

    now = dt.datetime(2026, 1, 1, 12, 0, 0, tzinfo=dt.UTC)
    first = build_search_results(_streams(), "query", now=now)
    second = build_search_results(_streams(), "query", now=now)
    assert first == second


def test_agent_mode_answer_carries_parseable_json_block():
    answer = build_agent_mode_search_answer(_streams(), "red truck")

    assert "```json" in answer
    start = answer.index("```json") + len("```json")
    payload = json.loads(answer[start : answer.index("```", start)].strip())
    assert len(payload["data"]) == 2


def test_agent_mode_answer_empty_index_is_honest():
    answer = build_agent_mode_search_answer({}, "red truck")
    assert "```json" not in answer
    assert "No matching clips" in answer


def test_frames_response_shape_matches_overlay_contract():
    payload = build_frames_response("cam-1", "2026-01-01T00:00:00.000Z")

    (frame,) = payload["frames"]
    assert frame["timestamp"] == "2026-01-01T00:00:00.000Z"
    assert len(frame["metadata"]["objects"]) == 2
    for obj in frame["metadata"]["objects"]:
        assert obj["id"] and obj["type"]
        bbox = obj["bbox"]
        assert 0 <= bbox["leftX"] < bbox["rightX"] <= 1
        assert 0 <= bbox["topY"] < bbox["bottomY"] <= 1


def test_kibana_dashboards_shape():
    payload = build_kibana_dashboards()
    assert payload["total"] == len(payload["saved_objects"]) == 1
    (dashboard,) = payload["saved_objects"]
    assert dashboard["type"] == "dashboard"
    assert dashboard["attributes"]["title"]
