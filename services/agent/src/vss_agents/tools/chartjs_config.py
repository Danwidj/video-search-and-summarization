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
import math
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
MAX_SERIES = 3
MAX_POINTS = 200
# A bubble's radius runs from the smallest to the largest, scaled by the square root of its report count.
BUBBLE_MIN_RADIUS = 4.0
BUBBLE_MAX_RADIUS = 24.0
# The fill of a bubble is its colour at 70% opacity.
BUBBLE_FILL_SUFFIX = "B3"

Figure = Annotated[float, Field(allow_inf_nan=False)]


class ChartJsKind(StrEnum):
    BAR = "bar"
    STACKED_BAR = "stacked_bar"
    HORIZONTAL_BAR = "horizontal_bar"
    DONUT = "donut"
    LINE = "line"
    AREA = "area"
    # A bar on the left axis and a line on the right: series 0 is the bar, series 1 the line.
    COMBO_DUAL_AXIS = "combo_dual_axis"
    # Stacked bars, one segment per severity: series high, medium, low, in that order.
    STACKED_BY_SEVERITY = "stacked_by_severity"


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
    y2_label: str = Field(default="", max_length=120)
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
        if self.kind is ChartJsKind.COMBO_DUAL_AXIS and len(self.series) != 2:
            raise ValueError("a dual-axis chart has two series: the bar, then the line")
        if self.kind is ChartJsKind.STACKED_BY_SEVERITY and len(self.series) != 3:
            raise ValueError("a severity stack has three series: high, medium, low")
        if self.y2_label and self.kind is not ChartJsKind.COMBO_DUAL_AXIS:
            raise ValueError("y2_label is for a dual-axis chart only")
        if self.slice_colors is not None:
            if self.kind is not ChartJsKind.DONUT:
                raise ValueError("slice_colors is for a donut chart only")
            if len(self.slice_colors) != count:
                raise ValueError("slice_colors needs one colour per label")
            for color in self.slice_colors:
                if not _is_hex(color):
                    raise ValueError(f"{color!r} is not a 6-digit hex colour")
        return self


class BubblePoint(BaseModel):
    """One bubble: its figures are x, y and count (the reports behind it) as given; the radius is scaled from count."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    x: Figure
    y: Figure
    count: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    color: str | None = Field(default=None, pattern=HEX_COLOR)


class ChartJsBubbleData(BaseModel):
    """A bubble chart: x, y and a radius scaled from each point's report count, by this code and never by the model."""

    model_config = ConfigDict(extra="forbid")

    output: Literal["chartjs"]
    kind: Literal["bubble"]
    title: str = Field(default="", max_length=200)
    x_label: str = Field(default="", max_length=120)
    y_label: str = Field(default="", max_length=120)
    series_label: str = Field(default="Reports", min_length=1, max_length=80)
    points: list[BubblePoint] = Field(min_length=1, max_length=MAX_POINTS)


def _is_hex(color: str) -> bool:
    return len(color) == 7 and color[0] == "#" and all(char in "0123456789abcdefABCDEF" for char in color[1:])


def _text_option(text: str) -> dict[str, Any]:
    return {"display": bool(text), "text": text}


def bubble_radius(count: float, largest: float) -> float:
    """The radius for a report count: area grows with the count, so the largest point gets the largest radius."""
    if largest <= 0:
        return BUBBLE_MIN_RADIUS
    return BUBBLE_MIN_RADIUS + (BUBBLE_MAX_RADIUS - BUBBLE_MIN_RADIUS) * math.sqrt(count / largest)


def _linear_axis(title: str, *, begin_at_zero: bool) -> dict[str, Any]:
    # grace leaves room past the outermost bubbles, so a bubble at the edge of the data is not cut off by the axis.
    return {
        "type": "linear",
        "beginAtZero": begin_at_zero,
        "grace": "10%",
        "title": _text_option(title),
        "ticks": {"precision": 0},
    }


def bubble_config(data: ChartJsBubbleData) -> dict[str, Any]:
    """The Chart.js bubble configuration: each point's x, y, count and label as given, its radius scaled from its count."""
    largest = max(point.count for point in data.points)
    colors = [point.color or DEFAULT_COLORS[0] for point in data.points]
    dataset = {
        "label": data.series_label,
        "data": [
            {
                "x": point.x,
                "y": point.y,
                "r": bubble_radius(point.count, largest),
                "count": point.count,
                "label": point.label,
            }
            for point in data.points
        ],
        "backgroundColor": [f"{color}{BUBBLE_FILL_SUFFIX}" for color in colors],
        "borderColor": colors,
        "borderWidth": 1,
    }
    return {
        "type": "bubble",
        "data": {"datasets": [dataset]},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {"legend": {"position": "bottom"}, "title": _text_option(data.title)},
            "scales": {
                "x": _linear_axis(data.x_label, begin_at_zero=False),
                "y": _linear_axis(data.y_label, begin_at_zero=True),
            },
        },
    }


def combo_dual_axis_config(data: ChartJsChartData) -> dict[str, Any]:
    """A bar on the left axis and a line on the right axis, both titled. The figures are the series' values as given."""
    bars, line = data.series
    bar_color = bars.color or DEFAULT_COLORS[0]
    line_color = line.color or DEFAULT_COLORS[1]
    datasets: list[dict[str, Any]] = [
        {
            "label": bars.label,
            "data": list(bars.values),
            "backgroundColor": bar_color,
            "borderRadius": 4,
            "maxBarThickness": 48,
            "yAxisID": "y",
            # Chart.js draws a lower order on top: the line is over the bars, so no point is hidden under its bar.
            "order": 2,
        },
        {
            "type": "line",
            "label": line.label,
            "data": list(line.values),
            "borderColor": line_color,
            "backgroundColor": line_color,
            "fill": False,
            "tension": 0,
            "pointRadius": 3,
            "yAxisID": "y1",
            "order": 1,
        },
    ]
    return {
        "type": "bar",
        "data": {"labels": list(data.labels), "datasets": datasets},
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "interaction": {"mode": "index", "intersect": False},
            "plugins": {"legend": {"position": "bottom"}, "title": _text_option(data.title)},
            "scales": {
                # offset centres each category between its ticks, so the line's points sit over the centres of the bars.
                "x": {"offset": True, "title": _text_option(data.x_label)},
                "y": {
                    "position": "left",
                    "beginAtZero": True,
                    "title": _text_option(data.y_label),
                    "ticks": {"precision": 0},
                },
                "y1": {
                    "position": "right",
                    "beginAtZero": True,
                    "title": _text_option(data.y2_label),
                    "grid": {"drawOnChartArea": False},
                },
            },
        },
    }


def chartjs_config(data: ChartJsChartData | ChartJsBubbleData) -> dict[str, Any]:
    """The Chart.js configuration for one chart: plain JSON, with the figures exactly as given."""
    if isinstance(data, ChartJsBubbleData):
        return bubble_config(data)
    if data.kind is ChartJsKind.COMBO_DUAL_AXIS:
        return combo_dual_axis_config(data)
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

    is_bar = data.kind in (
        ChartJsKind.BAR,
        ChartJsKind.STACKED_BAR,
        ChartJsKind.HORIZONTAL_BAR,
        ChartJsKind.STACKED_BY_SEVERITY,
    )
    stacked = data.kind in (ChartJsKind.STACKED_BAR, ChartJsKind.STACKED_BY_SEVERITY) or (
        data.kind is ChartJsKind.AREA and len(data.series) > 1
    )
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

    severity_stack = data.kind is ChartJsKind.STACKED_BY_SEVERITY
    if severity_stack:
        # Chart.js stacks the first dataset at the bottom: low is drawn first, so high is on top.
        datasets.reverse()
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
    if severity_stack:
        # The legend still reads high, medium, low.
        options["plugins"]["legend"]["reverse"] = True
    if horizontal:
        options["indexAxis"] = "y"
    return {
        "type": "bar" if is_bar else "line",
        "data": {"labels": labels, "datasets": datasets},
        "options": options,
    }
