from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from r2_videos import category_matches


def test_exact_category_precedes_related_fallbacks():
    keys = [
        "anomaly/abuse/Abuse001_x264.mp4",
        "anomaly/fighting/Fighting001_x264.mp4",
        "anomaly/animal_attacks/Animal001_x264.mp4",
        "anomaly/road_accidents/RoadAccidents001_x264.mp4",
    ]
    assert category_matches("fighting", keys) == [keys[1]]
    assert category_matches("animal", keys) == [keys[2]]
    assert category_matches("road accident", keys) == [keys[3]]
    assert category_matches("explosion", keys) == []


def test_detail_automatically_loads_category_video():
    key = "anomaly/animal_attacks/Animal001_x264.mp4"
    with (
        patch("r2_videos.configured", return_value=True),
        patch("r2_videos.list_video_keys", return_value=[key]),
        patch("r2_videos.playback_url", return_value="https://example.invalid/video.mp4"),
    ):
        app = AppTest.from_file("../pages/2_Report_Review.py")
        app.query_params["report"] = "Animal007"  # real animal incident: starts at 00:00:21
        app.run()
        assert not app.exception
        assert app.get("video")[0].proto.start_time == 21
        assert app.get("video")[0].proto.url == "https://example.invalid/video.mp4"
        assert any("not the actual event" in c.value for c in app.caption)
