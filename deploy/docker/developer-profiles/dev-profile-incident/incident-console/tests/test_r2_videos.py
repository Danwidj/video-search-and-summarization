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

from unittest.mock import patch

from fixtures.dashboard_seed import load_seed
from local_reports import LocalReports
from r2_videos import category_matches, map_incidents_to_video_keys


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


def test_detail_automatically_maps_exact_video():
    key = "anomaly/animal_attacks/Animal001_x264.mp4"
    with (
        patch("local_reports.configured", return_value=True),
        patch("local_reports.list_video_keys", return_value=[key]),
        patch("local_reports.playback_url", return_value="https://example.invalid/video.mp4"),
    ):
        handle = LocalReports({})
        video = handle.get_video("Animal001")
        assert video["R2_Key"] == key
        assert video["Filepath"] == "https://example.invalid/video.mp4"


def test_each_incident_gets_a_distinct_video_key():
    incidents = load_seed()["Incident"][:4]
    keys = [f"anomaly/burglary/Burglary00{n}_x264.mp4" for n in range(1, 5)]
    mapping = map_incidents_to_video_keys(incidents, keys)
    assert set(mapping) == {row["Incident_ID"] for row in incidents}
    assert len(mapping.values()) == len(set(mapping.values()))


def test_fallback_keeps_video_keys_unique_when_category_is_short():
    incidents = [{"Incident_ID": f"A{n}", "Filename": f"Animal{n:03d}.mp4", "Type": "animal"} for n in range(1, 4)]
    mapping = map_incidents_to_video_keys(incidents, ["animal/Animal001.mp4", "animal/Animal002.mp4", "other/Clip.mp4"])
    assert len(mapping) == 3
    assert len(set(mapping.values())) == 3
