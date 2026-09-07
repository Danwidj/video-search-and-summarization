"""Report-detail presentation. No seed generation or storage-provider assumptions."""

from __future__ import annotations

import html
import math
import re

import streamlit as st

import config
from incident_report import INCIDENT_TYPES, seconds_to_timestamp
from ui import video_playback_url

STATUS_LABELS = {"unreviewed": "Unreviewed", "under review": "Under Review", "verified": "Verified"}
SEVERITY_LABELS = {1: "Very Low", 2: "Low", 3: "Moderate", 4: "High", 5: "Critical"}
SEVERITY_COLORS = {1: "#36954c", 2: "#16856c", 3: "#bd8500", 4: "#df6818", 5: "#cf3434"}
FIELD_MAP = {
    "ID": "id",
    "Type": "incident_type",
    "Start_Timestamp": "incident_start",
    "End_Timestamp": "incident_end",
    "Duration": "duration",
    "Description": "description",
    "Severity_Level": "severity",
    "Confidence_Score": "confidence",
}


def seconds(value):
    """Strict parser: missing/invalid values stay missing rather than becoming 0."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"\d+(?::[0-5]\d){0,2}", text):
        return None
    result = 0
    for part in text.split(":"):
        result = result * 60 + int(part)
    return result


def normalized(record):
    fields = {key: record.get(key, record.get(legacy)) for key, legacy in FIELD_MAP.items()}
    for key in ("Start_Timestamp", "End_Timestamp", "Duration"):
        fields[key] = seconds(fields[key])
    start, end = fields["Start_Timestamp"], fields["End_Timestamp"]
    # Legacy database has no duration column; derive only from supplied bounds.
    if "Duration" not in record and "duration" not in record and start is not None and end is not None and end >= start:
        fields["Duration"] = end - start
    return fields


def confidence_label(value):
    try:
        number = float(value)
        return f"{number:.1%}" if math.isfinite(number) and 0 <= number <= 1 else "Not supplied / invalid"
    except (TypeError, ValueError):
        return "Not supplied"


def time_label(value):
    return seconds_to_timestamp(value) if value is not None else "Not supplied"


def severity_label(value):
    return f"{value}/5 — {SEVERITY_LABELS[value]}" if value in SEVERITY_LABELS else "Not supplied / invalid"


def pill(text, color):
    st.markdown(
        f'<span style="display:inline-block;border-radius:20px;padding:4px 12px;background:{color}15;color:{color};border:1px solid {color}40;font-size:12px;font-weight:600">{html.escape(str(text))}</span>',
        unsafe_allow_html=True,
    )


def video_panel(record, video, fields):
    st.markdown("##### Source footage")
    url = video_playback_url({"r2_key": video["Filepath"]}) if video and video.get("Filepath") else None
    if not url and video:
        url = video_playback_url(video)
    start, end = fields["Start_Timestamp"], fields["End_Timestamp"]
    duration = seconds(video.get("Duration", video.get("duration"))) if video else None
    if url:
        target = st.session_state.get(f"seek_{record['id']}", start or 0)
        if duration is not None and target >= duration:
            st.warning("Incident timestamp is outside the supplied video duration. Playback starts at 0:00.")
            target = 0
        try:
            st.video(url, start_time=target)
        except Exception:
            st.error("Video could not be loaded. The source may be missing or inaccessible.")
        st.caption("If playback fails, the file may be unavailable or its access link may have expired.")
        st.link_button("Open source footage", url)
    else:
        st.info("Source footage unavailable. No playable file is linked to this report.", icon="🎥")
    if start is None:
        st.caption("Incident start is missing or invalid; playback defaults to 0:00.")
    elif record.get("incident_start_confirmed") is False:
        st.caption("The supplied start timestamp has not been confirmed. Playback opens at that timestamp for review.")
    st.markdown(f"**Incident window:** {time_label(start)} → {time_label(end)}")
    a, b = st.columns(2)
    for column, label, target in ((a, "Jump to incident start", start), (b, "Jump to incident end", end)):
        if column.button(label, disabled=not url or target is None, key=f"{label}_{record['id']}"):
            st.session_state[f"seek_{record['id']}"] = target
            st.rerun()
    if start is not None and end is not None and end < start:
        st.warning("Incident end precedes incident start. Correct the timestamps before verifying.")
    if duration and start is not None and end is not None and 0 <= start <= end <= duration:
        left, width = start / duration * 100, (end - start) / duration * 100
        st.markdown(
            f'<div role="img" aria-label="Incident range within full video" style="height:9px;background:#e6e9ed;border-radius:8px;overflow:hidden"><div style="margin-left:{left}%;width:{width}%;height:100%;background:#76b900"></div></div>',
            unsafe_allow_html=True,
        )
        st.caption(f"Flagged range within full footage · 0:00 — {time_label(duration)}")
    with st.expander("Video details"):
        st.caption("Source file")
        st.text(
            (video or {}).get("filename") or (video or {}).get("r2_key") or "Linked video" if url else "Not supplied"
        )
        st.caption(f"Video duration: {time_label(duration)}")


def edit_form(handle, record, fields):
    with st.form(f"edit_detail_{record['id']}", border=False):
        st.caption("Incident ID")
        st.text(str(fields["ID"]))
        types = list(dict.fromkeys([fields["Type"], *INCIDENT_TYPES]))
        kind = st.selectbox("Incident type", types, format_func=lambda v: v or "Not supplied")
        a, b = st.columns(2)
        start = a.text_input(
            "Incident Start (seconds or mm:ss)",
            value="" if fields["Start_Timestamp"] is None else time_label(fields["Start_Timestamp"]),
        )
        end = b.text_input(
            "Incident End (seconds or mm:ss)",
            value="" if fields["End_Timestamp"] is None else time_label(fields["End_Timestamp"]),
        )
        st.caption(f"Duration: {time_label(fields['Duration'])} · Recalculated from start and end when saved")
        description = st.text_area("Description", value=fields["Description"] or "", height=160)
        severity = st.selectbox(
            "Severity Level",
            [None, 1, 2, 3, 4, 5],
            index=[None, 1, 2, 3, 4, 5].index(fields["Severity_Level"])
            if fields["Severity_Level"] in SEVERITY_LABELS
            else 0,
            format_func=severity_label,
        )
        confidence = st.text_input(
            "Confidence Score (0–1; blank if missing)",
            value="" if fields["Confidence_Score"] is None else str(fields["Confidence_Score"]),
        )
        confirmed = st.checkbox("Start timestamp confirmed", value=bool(record.get("incident_start_confirmed")))
        editor = st.text_input("Edited by", placeholder="Your name")
        save_col, cancel_col = st.columns(2)
        save = save_col.form_submit_button("Save changes", type="primary", width="stretch")
        cancel = cancel_col.form_submit_button("Cancel", width="stretch")
    if cancel:
        st.session_state["detail_close_edit"] = record["id"]
        st.rerun()
    if save:
        try:
            start_s, end_s = seconds(start), seconds(end)
            if (start.strip() and start_s is None) or (end.strip() and end_s is None):
                raise ValueError("Use non-negative seconds, mm:ss or hh:mm:ss for timestamps.")
            if start_s is not None and end_s is not None and end_s < start_s:
                raise ValueError("Incident end must be at or after incident start.")
            conf = float(confidence) if confidence.strip() else None
            if conf is not None and (not math.isfinite(conf) or not 0 <= conf <= 1):
                raise ValueError("Confidence must be between 0 and 1, or blank.")
            if confirmed and start_s is None:
                raise ValueError("Supply a start timestamp before confirming it.")
            if not editor.strip():
                raise ValueError("Enter your name to save changes.")
        except ValueError as exc:
            st.error(str(exc))
        else:
            try:
                handle.update_report(
                    record["id"],
                    fields={
                        "incident_type": kind,
                        "incident_start": seconds_to_timestamp(start_s) if start_s is not None else None,
                        "incident_end": seconds_to_timestamp(end_s) if end_s is not None else None,
                        "description": description,
                        "severity": severity,
                        "confidence": conf,
                        "incident_start_confirmed": confirmed,
                    },
                    edited_by=editor.strip(),
                )
            except Exception:
                st.error("Changes could not be saved. Your entries remain here; please retry.")
            else:
                st.session_state.pop(f"seek_{record['id']}", None)
                st.session_state["detail_notice"] = "Report changes saved."
                st.session_state["detail_close_edit"] = record["id"]
                st.rerun()


def render_detail(handle, record, video):
    fields = normalized(record)
    left, right = st.columns([1.1, 1], gap="large")
    with left, st.container(border=True):
        if callable(video):
            video = video()
        video_panel(record, video, fields)
    with right, st.container(border=True):
        st.subheader(fields["Type"] or "Incident type not supplied")
        st.caption(f"Report #{record['id']}")
        status = record.get("status")
        pill(
            STATUS_LABELS.get(status, "Status not supplied").upper(),
            {"verified": "#16854a", "under review": "#ac7800"}.get(status, "#667085"),
        )
        a, b = st.columns(2)
        with a:
            pill(severity_label(fields["Severity_Level"]), SEVERITY_COLORS.get(fields["Severity_Level"], "#667085"))
        b.markdown(f"**Confidence:** {confidence_label(fields['Confidence_Score'])}")
        st.markdown("##### AI Summary")
        st.info("AI summary not yet generated for this incident.", icon="✨")
        heading, action = st.columns([2, 1])
        heading.markdown("##### Incident fields")
        with action:
            edit = st.toggle("Edit fields", key=f"detail_edit_{record['id']}")
        if edit:
            st.caption("Edit the fields below, then save or cancel. The incident ID stays fixed.")
            edit_form(handle, record, fields)
        else:

            def field(label, value, help_text=None):
                st.caption(label, help=help_text)
                st.text(str(value) if value is not None and value != "" else "Not supplied")

            identity, category = st.columns(2)
            with identity:
                field("Incident ID", fields["ID"])
            with category:
                field("Type", fields["Type"])
            start_col, end_col, duration_col = st.columns(3)
            with start_col:
                field("Incident Start", time_label(fields["Start_Timestamp"]))
            with end_col:
                field("Incident End", time_label(fields["End_Timestamp"]))
            with duration_col:
                field("Duration", time_label(fields["Duration"]))
            field("Description", fields["Description"])
            severity_col, confidence_col = st.columns(2)
            with severity_col:
                field(
                    "Severity Level",
                    severity_label(fields["Severity_Level"]),
                    "Full severity rubric is not available in this checkout.",
                )
            with confidence_col:
                field("Confidence Score", confidence_label(fields["Confidence_Score"]))
        st.divider()
        st.markdown("##### Verification")
        with st.form(f"status_detail_{record['id']}"):
            options = list(STATUS_LABELS)
            chosen = st.selectbox(
                "Review status",
                options,
                index=options.index(status) if status in options else 0,
                format_func=STATUS_LABELS.get,
            )
            reviewer = st.text_input("Reviewed by", placeholder="Your name")
            submitted = st.form_submit_button("Save review status", type="primary", disabled=edit)
        if edit:
            st.caption("Finish field editing before changing review status.")
        if submitted:
            if not reviewer.strip():
                st.error("Enter your name to change review status.")
            elif chosen == status:
                st.info("This report already has the selected status.")
            elif (
                chosen == "verified"
                and fields["Start_Timestamp"] is not None
                and fields["End_Timestamp"] is not None
                and fields["End_Timestamp"] < fields["Start_Timestamp"]
            ):
                st.error("Correct the reversed incident timestamps before verifying.")
            else:
                try:
                    handle.set_report_review_status(
                        record["id"],
                        status=chosen,
                        reviewed_by=reviewer.strip(),
                        notify_threshold=config.severity_notify_threshold(),
                    )
                except Exception:
                    st.error("Review status could not be saved. Please retry.")
                else:
                    st.session_state["detail_notice"] = f"Report marked {STATUS_LABELS[chosen]}."
                    st.rerun()
        if record.get("verified_by"):
            st.caption(f"Verified by {record['verified_by']} · {record.get('verified_at') or 'Time not supplied'}")
        elif record.get("edited_by"):
            st.caption(f"Last updated by {record['edited_by']} · {record.get('edited_at') or 'Time not supplied'}")
