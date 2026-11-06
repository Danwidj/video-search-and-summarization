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

"""Chart.js configurations for dashboard charts, built by ``chart_generator``.

The console sends the figures it read from the database, the chart kind and the colours of the
console's own palette. This module places those numbers and labels into a plain JSON Chart.js
configuration (type, data, options). It never computes, rounds or reorders a figure, and it writes
no JavaScript: every value is a string, a number, a boolean or a list or object of these, so the
browser can run the configuration with ``new Chart(...)`` and nothing else.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
# Used only when the caller sends no colour. The console always sends its own palette.
DEFAULT_COLORS = ("#174f3b", "#d9754c", "#12211b", "#765300", "#6b7280")
MAX_CATEGORIES = 200
MAX_SERIES = 2

Figure = Annotated[float, Field(allow_inf_nan=False)]


class ChartJsKind(StrEnum):
    BAR = "bar"
    STACKED_BAR = "stacked_bar"
    HORIZONTAL_BAR = "horizontal_bar"
    DONUT = "donut"
    LINE = "line"
    AREA = "area"


class ChartJsSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    values: list[Figure] = Field(max_length=MAX_CATEGORIES)
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class ChartJsChartData(BaseModel):
    """One Chart.js chart. ``output`` marks it, so it is never mistaken for a PNG request."""

    model_config = ConfigDict(extra="forbid")

    output: Literal["chartjs"]
    kind: ChartJsKind
    title: str = Field(default="", max_length=200)
    x_label: str = Field(default="", max_length=120)
    y_label: str = Field(default="", max_length=120)
    labels: list[str] = Field(max_length=MAX_CATEGORIES)
    series: list[ChartJsSeries] = Field(min_length=1, max_length=MAX_SERIES)
    slice_colors: list[str] | None = Field(default=None, max_length=MAX_CATEGORIES)

    @model_validator(mode="after")
    def _shapes_agree(self) -> ChartJsChartData:
        count = len(self.labels)
        for series in self.series:
            if len(series.values) != count:
                raise ValueError(f"series {series.label!r} has {len(series.values)} values for {count} labels")
        if self.kind is ChartJsKind.DONUT and len(self.series) != 1:
            raise ValueError("a donut chart has exactly one series")
        if self.slice_colors is not None:
            if self.kind is not ChartJsKind.DONUT:
                raise ValueError("slice_colors is for a donut chart only")
            if len(self.slice_colors) != count:
                raise ValueError("slice_colors needs one colour per label")
            for color in self.slice_colors:
                if not _is_hex(color):
                    raise ValueError(f"{color!r} is not a 6-digit hex colour")
        return self


def _is_hex(color: str) -> bool:
    return len(color) == 7 and color[0] == "#" and all(char in "0123456789abcdefABCDEF" for char in color[1:])


def _text_option(text: str) -> dict[str, Any]:
    return {"display": bool(text), "text": text}


def chartjs_config(data: ChartJsChartData) -> dict[str, Any]:
    """The Chart.js configuration for one chart: plain JSON, with the figures exactly as given."""
    labels = list(data.labels)
    palette = DEFAULT_COLORS
    if data.kind is ChartJsKind.DONUT:
        slice_colors = data.slice_colors or [palette[index % len(palette)] for index in range(len(labels))]
        series = data.series[0]
        return {
            "type": "doughnut",
            "data": {
                "labels": labels,
                "datasets": [
                    {
                        "label": series.label,
                        "data": list(series.values),
                        "backgroundColor": list(slice_colors),
                        "borderColor": "#ffffff",
                        "borderWidth": 2,
                    }
                ],
            },
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "cutout": "60%",
                "plugins": {"legend": {"position": "bottom"}, "title": _text_option(data.title)},
            },
        }

    is_bar = data.kind in (ChartJsKind.BAR, ChartJsKind.STACKED_BAR, ChartJsKind.HORIZONTAL_BAR)
    stacked = data.kind is ChartJsKind.STACKED_BAR or (data.kind is ChartJsKind.AREA and len(data.series) > 1)
    datasets: list[dict[str, Any]] = []
    for index, series in enumerate(data.series):
        color = series.color or palette[index % len(palette)]
        if is_bar:
            dataset: dict[str, Any] = {
                "label": series.label,
                "data": list(series.values),
                "backgroundColor": color,
                "borderRadius": 4,
                "maxBarThickness": 48,
            }
        elif data.kind is ChartJsKind.AREA:
            # An eight-digit hex is the same colour at 20% opacity, so a stacked area keeps its outline.
            dataset = {
                "label": series.label,
                "data": list(series.values),
                "borderColor": color,
                "backgroundColor": f"{color}33",
                "fill": True,
                "tension": 0,
                "pointRadius": 2,
            }
        else:
            dataset = {
                "label": series.label,
                "data": list(series.values),
                "borderColor": color,
                "backgroundColor": color,
                "fill": False,
                "tension": 0,
                "pointRadius": 3,
            }
        datasets.append(dataset)

    horizontal = data.kind is ChartJsKind.HORIZONTAL_BAR
    value_axis, category_axis = ("x", "y") if horizontal else ("y", "x")
    scales: dict[str, Any] = {
        category_axis: {"stacked": stacked, "title": _text_option(data.x_label)},
        value_axis: {
            "stacked": stacked,
            "beginAtZero": True,
            "title": _text_option(data.y_label),
            "ticks": {"precision": 0},
        },
    }
    options: dict[str, Any] = {
        "responsive": True,
        "maintainAspectRatio": False,
        "interaction": {"mode": "index", "intersect": False},
        "plugins": {"legend": {"position": "bottom"}, "title": _text_option(data.title)},
        "scales": scales,
    }
    if horizontal:
        options["indexAxis"] = "y"
    return {
        "type": "bar" if is_bar else "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": options,
    }
