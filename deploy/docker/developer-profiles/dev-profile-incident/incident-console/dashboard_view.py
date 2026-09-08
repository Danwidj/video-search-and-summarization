"""Dashboard presentation and pure analytics; no database or storage access."""

from __future__ import annotations

import html
from urllib.parse import quote

import altair as alt
import pandas as pd
import streamlit as st

from theme import BORDER, MUTED, SEVERITY_COLORS, SEVERITY_LABELS, TYPE_COLORS, severity_badge

COLORS = [SEVERITY_COLORS[level] for level in range(1, 6)]
INCIDENT_COLUMNS = [
    "Incident_ID",
    "Filename",
    "Type",
    "Start_Timestamp",
    "End_Timestamp",
    "Duration",
    "Description",
    "Severity",
    "Confidence_Score",
]


def frame(rows):
    return pd.DataFrame(rows).reindex(columns=INCIDENT_COLUMNS)


def from_reports(reports):
    """Adapt the existing verified-report response without changing its query."""
    rows = []
    for report in reports:
        start, end = report.get("incident_start"), report.get("incident_end")
        seconds = pd.to_timedelta([start, end], errors="coerce").total_seconds()
        duration = seconds[1] - seconds[0]
        rows.append(
            {
                "Incident_ID": report.get("id"),
                "Filename": report.get("filename"),
                "Type": report.get("incident_type"),
                "Start_Timestamp": start,
                "End_Timestamp": end,
                "Duration": duration if duration >= 0 else None,
                "Description": report.get("description"),
                "Severity": report.get("severity"),
                "Confidence_Score": report.get("confidence"),
            }
        )
    return frame(rows)


def review_queue(view):
    return view[view.Confidence_Score.isna() | (view.Confidence_Score < 0.7)].sort_values(
        ["Confidence_Score", "Severity", "Incident_ID"], ascending=[True, False, True], na_position="first"
    )


def related(rows, view):
    return pd.DataFrame([row for row in rows if row["Incident_ID"] in set(view.Incident_ID)])


def empty(message):
    st.info(message, icon="🔎")


def chart(data, mark, x, y, color=None, height=190):
    result = getattr(alt.Chart(data), mark)().encode(x=x, y=y, tooltip=list(data.columns))
    if color is not None:
        result = result.encode(color=color)
    st.altair_chart(result.properties(height=height).configure_view(stroke=None).configure_axis(gridColor=BORDER, labelColor=MUTED, titleColor=MUTED), width="stretch")


def metric(column, icon, title, value, help_text):
    with column:
        st.metric(f"{icon}  {title}", value)
        st.caption(help_text)


def render(df, entities, instruments, reports=None):
    st.markdown(
        """<style>
    [data-testid="stMain"] [data-testid="stMetric"] {box-shadow:0 4px 16px #172b4d08;border-top:3px solid #76b900;border-radius:12px;}
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {background:white;border-radius:12px;}
    </style>""",
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        a, b, c, d = st.columns([3, 3, 3, 1])
        types = a.multiselect(
            "Incident Types", sorted(df.Type.dropna().unique()), key="dash_types", placeholder="All types"
        )
        names = sorted({r["Name"] for r in instruments})
        selected = b.multiselect(
            "Instruments", names, key="dash_instruments", placeholder="All instruments", disabled=not names
        )
        lo, hi = c.select_slider("Severity Range", options=[1, 2, 3, 4, 5], value=(1, 5), key="dash_severity")

        def reset():
            for key in ("dash_types", "dash_instruments", "dash_severity"):
                st.session_state.pop(key, None)

        d.button("Reset", on_click=reset, width="stretch")
    mask = df.Severity.between(lo, hi)
    if types:
        mask &= df.Type.isin(types)
    if selected:
        mask &= df.Incident_ID.isin([r["Incident_ID"] for r in instruments if r["Name"] in selected])
    view = df[mask].copy()
    st.caption(
        f"{len(view)} of {len(df)} incidents · All metrics follow the filters · Confidence review threshold: below 70%"
    )
    cols = st.columns(3)
    metric(cols[0], "▦", "Total Logged Incidents", len(view), "Within the available data scope")
    metric(cols[1], "⚑", "Critical Alerts (Sev 4–5)", int((view.Severity >= 4).sum()), "Incidents at severity 4 or 5")
    confidence = view.Confidence_Score.dropna()
    metric(
        cols[2],
        "◎",
        "Avg Confidence Score",
        f"{confidence.mean():.0%}" if len(confidence) else "—",
        f"{len(confidence)} scored · {len(view) - len(confidence)} missing",
    )

    st.markdown("#### Trend & triage")
    a, b, c = st.columns([2, 1, 2], gap="medium")
    with a, st.container(border=True):
        st.markdown("##### Incidents Over Time")
        st.caption("Start_Timestamp · 30-second clip-offset buckets, not calendar dates")
        seconds = pd.to_timedelta(view.Start_Timestamp, errors="coerce").dt.total_seconds().dropna()
        if seconds.empty:
            empty("No valid start timestamps in this selection.")
        else:
            counts = (
                ((seconds // 30) * 30)
                .value_counts()
                .reindex(range(0, int(seconds.max() // 30 + 1) * 30, 30), fill_value=0)
                .sort_index()
            )
            data = counts.rename_axis("Clip start (seconds)").reset_index(name="Incidents")
            line = (
                alt.Chart(data)
                .mark_line(point=True, color="#76B900")
                .encode(
                    x=alt.X("Clip start (seconds):Q"),
                    y=alt.Y("Incidents:Q", axis=alt.Axis(tickMinStep=1)),
                    tooltip=list(data.columns),
                )
            )
            st.altair_chart(line.properties(height=190).configure_view(stroke=None).configure_axis(gridColor=BORDER, labelColor=MUTED, titleColor=MUTED), width="stretch")
    with b, st.container(border=True):
        st.markdown("##### Avg Incident Duration")
        durations = pd.to_numeric(view.Duration, errors="coerce").dropna()
        st.metric("◴  Duration", f"{durations.mean():.1f}s" if len(durations) else "—")
        st.caption(f"Based on {len(durations)} incident durations")
        if durations.empty:
            empty("No incident durations available.")
    with c, st.container(border=True):
        st.markdown("##### Low-Confidence Review Queue")
        queue = review_queue(view)
        st.caption(f"{len(queue)} need confidence review · Missing first, then lowest score; severity breaks ties")
        if queue.empty:
            empty("No missing or low confidence scores in this selection.")
        for row in queue.head(4).itertuples():
            score = "Missing confidence" if pd.isna(row.Confidence_Score) else f"{row.Confidence_Score:.0%} confidence"
            with st.container(key=f"queue_{row.Incident_ID}"):
                target = quote(str(row.Incident_ID), safe="")
                st.markdown(
                    f'<a class="queue-link" href="/?report={target}">↗&nbsp; {html.escape(str(row.Incident_ID))} · {html.escape(score)}</a>',
                    unsafe_allow_html=True,
                )
                st.markdown(f'<div class="queue-item">{severity_badge(row.Severity)} <span class="muted">{row.Description or "No description supplied"}</span></div>', unsafe_allow_html=True)
        if len(queue) > 4:
            st.caption(f"Showing 4 of {len(queue)} · Remaining incidents appear in the records log.")

    st.markdown("#### Categories & linked evidence")
    a, b, c, d = st.columns([1, 1, 1, 1.25], gap="medium")
    scale = alt.Scale(domain=[1, 2, 3, 4, 5], range=COLORS)
    with a, st.container(border=True):
        st.markdown("##### Incident Count by Category")
        if view.empty:
            empty("No incidents match these filters.")
        else:
            counts = view.Type.value_counts().rename_axis("Category").reset_index(name="Count")
            chart(counts, "mark_bar", "Count:Q", "Category:N", alt.Color("Category:N", scale=alt.Scale(domain=list(TYPE_COLORS), range=list(TYPE_COLORS.values())), legend=None))
    with b, st.container(border=True):
        st.markdown("##### Incidents by Severity Level")
        if view.empty:
            empty("No severity data in this selection.")
        else:
            counts = (
                view.Severity.value_counts()
                .reindex(range(1, 6), fill_value=0)
                .rename_axis("Severity")
                .reset_index(name="Count")
            )
            chart(counts, "mark_bar", "Severity:O", "Count:Q", alt.Color("Severity:O", scale=scale, legend=None))
    with c, st.container(border=True):
        st.markdown("##### Entity Type Breakdown")
        linked = related(entities, view)
        if linked.empty:
            empty("No linked entities available. Human, animal and unknown counts appear once entities are supplied.")
        else:
            counts = (
                linked.assign(Type=linked.Type.fillna("unknown").str.lower())
                .Type.value_counts()
                .reindex(["human", "animal", "unknown"], fill_value=0)
                .rename_axis("Entity type")
                .reset_index(name="Count")
            )
            counts = counts[counts.Count > 0]
            if counts.empty:
                empty("Entity rows are present, but no human, animal or unknown types are populated.")
                counts = None
            if counts is None:
                st.caption("Entity type values are missing in the current selection.")
            else:
                donut = (
                    alt.Chart(counts)
                    .mark_arc(innerRadius=48)
                    .encode(
                        theta="Count:Q",
                        color=alt.Color(
                            "Entity type:N",
                            scale=alt.Scale(domain=["human", "animal", "unknown"], range=["#435569", "#76b900", "#c8cfd8"]),
                            legend=alt.Legend(orient="bottom"),
                        ),
                        tooltip=["Entity type", "Count"],
                    )
                )
                st.altair_chart(donut.properties(height=190).configure_view(stroke=None), width="stretch")
                st.caption(f"{len(linked)} entity rows · IDs are scoped to each incident")
    with d, st.container(border=True):
        st.markdown("##### Threat Level vs Severity")
        linked = related(instruments, view)
        if linked.empty:
            empty(
                "No linked instruments in this selection. The matrix needs Threat_Level and parent incident Severity."
            )
        else:
            pairs = linked.merge(view[["Incident_ID", "Severity"]], on="Incident_ID")
            counts = (
                pairs.groupby(["Threat_Level", "Severity"])
                .size()
                .reindex(
                    pd.MultiIndex.from_product([range(1, 6), range(1, 6)], names=["Threat_Level", "Severity"]),
                    fill_value=0,
                )
                .reset_index(name="Count")
            )
            base = alt.Chart(counts).encode(
                x=alt.X("Severity:O", title="Incident severity"),
                y=alt.Y("Threat_Level:O", title="Instrument threat", sort="descending"),
                tooltip=["Threat_Level", "Severity", "Count"],
            )
            cells = base.mark_rect(stroke="white", strokeWidth=2).encode(
                color=alt.Color("Severity:O", scale=scale, legend=alt.Legend(title="Severity")),
                opacity=alt.condition("datum.Count > 0", alt.value(0.85), alt.value(0.12)),
            )
            labels = base.mark_text(color="#18212a").encode(text="Count:Q")
            st.altair_chart((cells + labels).properties(height=190), width="stretch")
            st.caption(
                f"{len(linked)} instrument links across {linked.Incident_ID.nunique()} incidents · Numbers count links; 0 means none."
            )
    legend = " · ".join(
        f'<span style="color:{SEVERITY_COLORS[level]}">●</span> {level} {SEVERITY_LABELS[level]}'
        for level in range(1, 6)
    )
    st.markdown(f'<div class="muted">Severity / threat scale: {legend}</div>', unsafe_allow_html=True)
    st.markdown("#### Filtered Records Log")
    if view.empty:
        empty("No records match. Reset filters to restore the available incidents.")
    else:
        table = view.rename(
            columns={
                "Incident_ID": "ID",
                "Type": "Incident Type",
                "Start_Timestamp": "Start",
                "End_Timestamp": "End",
                "Confidence_Score": "Confidence (%)",
            }
        ).copy()
        table["Confidence (%)"] = table["Confidence (%)"] * 100
        table = table[
            ["ID", "Incident Type", "Filename", "Start", "End", "Duration", "Severity", "Confidence (%)"]
        ].sort_values("Severity", ascending=False)
        table["ID"] = table["ID"].map(lambda value: f"/?report={quote(str(value))}")

        def severity_style(value):
            return (
                f"background-color: {SEVERITY_COLORS[int(value)]}; color: #ffffff; border-left: 4px solid {SEVERITY_COLORS[int(value)]}"
                if pd.notna(value) and 1 <= value <= 5
                else ""
            )

        numeric = ["Start", "End", "Duration", "Severity", "Confidence (%)"]
        table_style = (
            table.style
            .map(severity_style, subset=["Severity"])
            .set_properties(subset=numeric, **{"text-align": "right"})
            .set_properties(subset=["Filename"], **{"font-family": "ui-monospace, SFMono-Regular, monospace"})
            .set_table_styles([
                {"selector": "tbody tr:nth-child(even)", "props": [("background-color", "#f8fafc")]},
                {"selector": "th", "props": [("text-align", "left"), ("position", "sticky"), ("top", "0px")]},
            ])
        )
        st.dataframe(
            table_style,
            hide_index=True,
            width="stretch",
            column_config={
                "ID": st.column_config.LinkColumn("ID", display_text=r".*/\?report=(.*)"),
                "Confidence (%)": st.column_config.NumberColumn(format="%.0f%%"),
            },
        )
