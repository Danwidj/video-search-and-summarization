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

"""Unit tests for the Chart.js configurations built by ``chart_generator``."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from pydantic import ValidationError
import pytest

from vss_agents.tools.chart_generator import ChartGeneratorConfig
from vss_agents.tools.chart_generator import ChartGeneratorInput
from vss_agents.tools.chart_generator import chart_generator
from vss_agents.tools.chartjs_config import DEFAULT_COLORS
from vss_agents.tools.chartjs_config import ChartJsChartData
from vss_agents.tools.chartjs_config import chartjs_config

OFFICIAL = "#174f3b"
NOT_OFFICIAL = "#d9754c"


def chart(kind: str, series: list[dict], labels: list[str], **extra: object) -> ChartJsChartData:
    return ChartJsChartData.model_validate(
        {"output": "chartjs", "kind": kind, "labels": labels, "series": series, **extra}
    )


SPLIT = [
    {"label": "Official", "values": [9, 4, 1], "color": OFFICIAL},
    {"label": "Not yet official", "values": [5, 7, 2], "color": NOT_OFFICIAL},
]
LABELS = ["Road accident", "Burglary", "Explosion"]


def test_grouped_bar_places_the_figures_exactly_and_uses_the_given_colours():
    config = chartjs_config(
        chart("bar", SPLIT, LABELS, title="Reports by incident type", x_label="Incident type", y_label="Reports")
    )
    assert config["type"] == "bar"
    assert config["data"]["labels"] == LABELS
    datasets = config["data"]["datasets"]
    assert [d["label"] for d in datasets] == ["Official", "Not yet official"]
    assert datasets[0]["data"] == [9, 4, 1]
    assert datasets[1]["data"] == [5, 7, 2]
    assert [d["backgroundColor"] for d in datasets] == [OFFICIAL, NOT_OFFICIAL]
    assert config["options"]["scales"]["x"]["stacked"] is False
    assert config["options"]["scales"]["y"]["title"] == {"display": True, "text": "Reports"}
    assert config["options"]["plugins"]["title"] == {"display": True, "text": "Reports by incident type"}


def test_stacked_bar_stacks_both_axes():
    config = chartjs_config(chart("stacked_bar", SPLIT, LABELS))
    assert config["type"] == "bar"
    assert config["options"]["scales"]["x"]["stacked"] is True
    assert config["options"]["scales"]["y"]["stacked"] is True


def test_horizontal_bar_turns_the_index_axis_and_swaps_the_titles():
    config = chartjs_config(chart("horizontal_bar", SPLIT, LABELS, x_label="Incident type", y_label="Reports"))
    assert config["type"] == "bar"
    assert config["options"]["indexAxis"] == "y"
    # The category axis is the y axis here, so it carries the category label.
    assert config["options"]["scales"]["y"]["title"]["text"] == "Incident type"
    assert config["options"]["scales"]["x"]["title"]["text"] == "Reports"


def test_donut_has_one_dataset_and_the_given_slice_colours():
    slices = [{"label": "Reports", "values": [18, 15, 8]}]
    config = chartjs_config(
        chart(
            "donut", slices, ["Low (1-2)", "Medium (3)", "High (4-5)"], slice_colors=["#174f3b", "#765300", "#991b1b"]
        )
    )
    assert config["type"] == "doughnut"
    assert len(config["data"]["datasets"]) == 1
    assert config["data"]["datasets"][0]["data"] == [18, 15, 8]
    assert config["data"]["datasets"][0]["backgroundColor"] == ["#174f3b", "#765300", "#991b1b"]
    assert config["options"]["cutout"] == "60%"


def test_donut_without_slice_colours_uses_the_default_palette():
    config = chartjs_config(chart("donut", [{"label": "Reports", "values": [1, 2, 3]}], ["a", "b", "c"]))
    assert config["data"]["datasets"][0]["backgroundColor"] == list(DEFAULT_COLORS[:3])


def test_line_and_area_are_line_charts_and_only_a_multi_series_area_stacks():
    daily = [{"label": "Official", "values": [1, 0, 3], "color": OFFICIAL}]
    line = chartjs_config(chart("line", daily, ["Oct 1", "Oct 2", "Oct 3"]))
    assert line["type"] == "line"
    assert line["data"]["datasets"][0]["fill"] is False

    area = chartjs_config(chart("area", daily, ["Oct 1", "Oct 2", "Oct 3"]))
    assert area["type"] == "line"
    assert area["data"]["datasets"][0]["fill"] is True
    assert area["data"]["datasets"][0]["backgroundColor"] == f"{OFFICIAL}33"
    assert area["options"]["scales"]["y"]["stacked"] is False

    stacked_area = chartjs_config(chart("area", SPLIT[:2], ["Oct 1", "Oct 2", "Oct 3"]))
    assert stacked_area["options"]["scales"]["y"]["stacked"] is True


def test_every_config_is_plain_json_with_no_callbacks():
    for kind in ("bar", "stacked_bar", "horizontal_bar", "line", "area"):
        config = chartjs_config(chart(kind, SPLIT, LABELS, title="t", x_label="x", y_label="y"))
        text = json.dumps(config)  # raises for any non-JSON value, such as a function
        assert "function" not in text
    donut = chartjs_config(chart("donut", [{"label": "R", "values": [1, 2]}], ["a", "b"]))
    json.dumps(donut)


def test_figures_are_never_altered_even_when_they_are_large_or_zero():
    values = [0, 1, 999999, 3.5]
    config = chartjs_config(chart("bar", [{"label": "Reports", "values": values}], ["a", "b", "c", "d"]))
    assert config["data"]["datasets"][0]["data"] == values


def test_series_without_a_colour_get_the_default_palette():
    config = chartjs_config(chart("bar", [{"label": "Reports", "values": [1]}], ["a"]))
    assert config["data"]["datasets"][0]["backgroundColor"] == DEFAULT_COLORS[0]


@pytest.mark.parametrize(
    "payload",
    [
        # a series with the wrong number of values
        {"kind": "bar", "labels": ["a", "b"], "series": [{"label": "R", "values": [1]}]},
        # a donut with two series
        {"kind": "donut", "labels": ["a"], "series": [{"label": "R", "values": [1]}, {"label": "S", "values": [2]}]},
        # a colour that is not six-digit hex (no CSS or script injection)
        {"kind": "bar", "labels": ["a"], "series": [{"label": "R", "values": [1], "color": "red;}"}]},
        # slice colours on a bar chart
        {"kind": "bar", "labels": ["a"], "series": [{"label": "R", "values": [1]}], "slice_colors": ["#174f3b"]},
        # an unknown key
        {"kind": "bar", "labels": ["a"], "series": [{"label": "R", "values": [1]}], "options": {"responsive": False}},
        # a figure that is not finite
        {"kind": "bar", "labels": ["a"], "series": [{"label": "R", "values": [float("nan")]}]},
        # an unknown kind
        {"kind": "heatmap", "labels": ["a"], "series": [{"label": "R", "values": [1]}]},
    ],
)
def test_malformed_chart_requests_are_refused(payload):
    with pytest.raises(ValidationError):
        ChartJsChartData.model_validate({"output": "chartjs", **payload})


def test_a_chartjs_payload_is_not_mistaken_for_a_png_bar_request():
    parsed = ChartGeneratorInput.model_validate(
        {
            "charts_data": [
                {"output": "chartjs", "kind": "bar", "labels": ["a"], "series": [{"label": "R", "values": [1]}]}
            ]
        }
    )
    assert isinstance(parsed.charts_data[0], ChartJsChartData)


@pytest.mark.asyncio
async def test_the_tool_returns_a_config_without_needing_an_object_store():
    config = ChartGeneratorConfig(object_store_name=None)
    builder = AsyncMock()
    generator = chart_generator.__wrapped__(config, builder)
    function_info = await generator.__anext__()
    request = ChartGeneratorInput.model_validate(
        {
            "charts_data": [
                {"output": "chartjs", "kind": "bar", "labels": ["a", "b"], "series": [{"label": "R", "values": [3, 0]}]}
            ]
        }
    )
    outputs = await function_info.single_fn(request)
    assert len(outputs) == 1
    assert outputs[0].success is True
    assert outputs[0].object_store_key is None
    assert outputs[0].chart_config is not None
    assert outputs[0].chart_config["data"]["datasets"][0]["data"] == [3, 0]
