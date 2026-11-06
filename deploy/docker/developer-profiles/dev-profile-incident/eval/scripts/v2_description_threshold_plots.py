# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Plots for the exploratory description-threshold analysis, from its CSVs only.

    ~/.cache/vss-agent-venv/bin/python scripts/v2_description_threshold_plots.py
"""

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "methodology" / "description-threshold-sensitivity"
SERIES = (("gemma4-31b-openrouter", "Gemma 4 31B", "#2a78d6", "o"), ("omni-direct", "Nemotron 3 Nano Omni", "#eb6834", "s"),
          ("qwen35-9b-openrouter", "Qwen3.5-9B", "#1baf7a", "^"), ("nano-direct", "Cosmos 3 Nano", "#eda100", "D"),
          ("super-direct", "Cosmos 3 Super (incomplete)", "#e87ba4", "v"))
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED,
                     "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "text.color": INK})
rows = list(csv.DictReader((OUT / "per_model_pass_rates.csv").open()))
per = list(csv.DictReader((OUT / "per_description_scores.csv").open()))

fig, ax = plt.subplots(figsize=(9.5, 5.4), dpi=160)
for sid, name, colour, marker in SERIES:
    r = [x for x in rows if x["subject"] == sid]
    xs, ys = [float(x["threshold"]) for x in r], [100 * float(x["pass_rate_valid"]) for x in r]
    ax.plot(xs, ys, color=colour, marker=marker, markersize=7, linewidth=2, label=name, linestyle="--" if sid == "super-direct" else "-",
            markeredgecolor=SURFACE, markeredgewidth=1.2)
    if sid != "super-direct":
        ax.text(0.708, ys[-1], name, color=INK, va="center", fontsize=10)
ax.axvline(0.5, color=MUTED, linewidth=1)
ax.text(0.503, 79, "frozen 0.50", color=MUTED, fontsize=10)
ax.axvline(0.4, color=MUTED, linewidth=1, linestyle=":")
ax.text(0.403, 79, "exploratory 0.40", color=MUTED, fontsize=10)
ax.set(xlim=(0.28, 0.83), ylim=(0, 85), xlabel="Pass threshold on judge score", ylabel="Pass rate, valid judged descriptions (%)")
ax.set_xticks([0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70])
ax.grid(axis="y", color=GRID, linewidth=0.8)
ax.spines[["top", "right"]].set_visible(False)
ax.legend(frameon=False, loc="lower left", fontsize=9, ncol=2)
ax.set_title("The four complete models keep their order at every threshold (exploratory)", loc="left", fontsize=13, color=INK)
fig.tight_layout()
fig.savefig(OUT / "plots" / "pass_rate_vs_threshold.png")

fig, axes = plt.subplots(5, 1, figsize=(8.5, 8.6), dpi=160, sharex=True)
bins = [i / 20 for i in range(21)]
for ax, (sid, name, colour, _) in zip(axes, SERIES, strict=True):
    counts = defaultdict(int)
    vals = [float(x["score"]) for x in per if x["subject"] == sid and x["score"] != ""]
    ax.hist(vals, bins=[b - 0.025 for b in bins] + [1.025], color=colour, rwidth=0.8)
    ax.axvline(0.5, color=MUTED, linewidth=1)
    ax.axvline(0.4, color=MUTED, linewidth=1, linestyle=":")
    ax.text(0.995, 0.86, f"{name}, n={len(vals)}", transform=ax.transAxes, ha="right", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_ylabel("count", fontsize=9)
axes[-1].set_xlabel("Judge score (solid line = frozen 0.50, dotted = exploratory 0.40)")
axes[0].set_title("Scores cluster at the extremes, with few near the cutoff", loc="left", fontsize=13, color=INK)
fig.tight_layout()
fig.savefig(OUT / "plots" / "score_distribution.png")
