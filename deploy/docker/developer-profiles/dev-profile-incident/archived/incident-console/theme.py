"""Shared RISE UP presentation tokens and Streamlit styling."""

from __future__ import annotations

import html

import streamlit as st

BRAND = "#76B900"
BRAND_DARK = "#5C9200"
TEXT = "#17212B"
MUTED = "#667085"
BORDER = "#DCE3EA"
SURFACE = "#FFFFFF"
BACKGROUND = "#F4F6F8"
SEVERITY_COLORS = {1: "#2E7D5B", 2: "#4AAE7D", 3: "#D39A19", 4: "#E4742B", 5: "#C93C47"}
SEVERITY_LABELS = {1: "Very Low", 2: "Low", 3: "Moderate", 4: "High", 5: "Critical"}
# Keys cover both the original capstone ground-truth taxonomy (animal / burglary
# / …) and the Supabase 8-mock taxonomy (warehouse safety / equipment / …).
# Unknown types fall back to the "" entry.
TYPE_COLORS = {
    "animal": "#4AAE7D",
    "road accident": "#D39A19",
    "burglary": "#7B61A8",
    "explosion": "#C93C47",
    "fighting": "#E4742B",
    "robbery": "#7B61A8",
    "vandalism": "#4D82A8",
    "stealing": "#8B6F47",
    "shooting": "#C93C47",
    "abuse": "#A05A7D",
    "warehouse safety": "#4AAE7D",
    "equipment": "#4D82A8",
    "pedestrian": "#D39A19",
    "traffic": "#E4742B",
    "structural": "#7B61A8",
    "other": "#8B95A1",
    "": "#AAB4BF",
}

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
:root {{ --brand:{BRAND}; --brand-dark:{BRAND_DARK}; --text:{TEXT}; --muted:{MUTED}; --border:{BORDER}; --surface:{SURFACE}; --bg:{BACKGROUND}; }}
html, body, [data-testid="stAppViewContainer"] {{ font-family:Inter,system-ui,-apple-system,sans-serif!important; background:var(--bg)!important; color:var(--text)!important; }}
[data-testid="stMainBlockContainer"] {{ max-width:1480px; padding-top:2rem; }}
section[data-testid="stSidebar"] {{ background:var(--surface)!important; border-right:1px solid var(--border)!important; }}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color:var(--muted); }}
section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {{ display:inline-block; line-height:1.35; }}
h1,h2,h3,h4,h5,h6 {{ font-family:inherit!important; color:var(--text)!important; letter-spacing:-.02em!important; }} h1 {{ font-size:2rem!important; }} h2 {{ font-size:1.35rem!important; }} h3 {{ font-size:1.05rem!important; }}
hr {{ border-color:var(--border)!important; }}
div.stButton > button {{ border-radius:8px!important; border:1px solid var(--border)!important; min-height:2.35rem; font-weight:600!important; }}
div.stButton > button[kind="primary"] {{ background:var(--brand)!important; border-color:var(--brand)!important; color:#fff!important; }} div.stButton > button[kind="primary"]:hover {{ background:var(--brand-dark)!important; }}
input, textarea, [data-baseweb="select"] {{ border-radius:8px!important; border-color:var(--border)!important; }} input:focus, textarea:focus {{ border-color:var(--brand)!important; box-shadow:0 0 0 2px #76b9002b!important; }}
[data-testid="stMetric"] {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1rem 1.1rem; box-shadow:0 5px 18px #172b4d0b; }} [data-testid="stMetricValue"] {{ color:var(--text)!important; font-weight:700!important; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:var(--border)!important; border-radius:12px!important; background:var(--surface); box-shadow:0 5px 18px #172b4d09; }}
.rise-header {{ padding:.45rem 0 1rem; border-bottom:1px solid var(--border); margin-bottom:1.25rem; overflow:visible!important; }} .wordmark {{ display:inline-block; line-height:1.5; font-size:1.25rem; font-weight:700; letter-spacing:.12em; padding:.05rem 0; overflow:visible!important; }} .nvidia-pill {{ display:inline-block; margin-left:.6rem; padding:.25rem .6rem; border-radius:999px; background:#edf7dd; color:#4f8100; font-size:.68rem; font-weight:700; letter-spacing:.08em; line-height:1.2; }} .tagline {{ color:var(--muted); margin-top:.35rem; font-size:.9rem; line-height:1.4; }} .meta-line,.muted {{ color:var(--muted); font-size:.78rem; }}
.section-heading {{ margin:1.2rem 0 .65rem; font-size:1.05rem; font-weight:700; }}
.alert {{ display:flex; gap:.65rem; align-items:flex-start; padding:.8rem 1rem; border:1px solid; border-left-width:4px; border-radius:10px; margin:.5rem 0 1rem; font-size:.88rem; }} .alert-info {{ background:#eff6ff; border-color:#bfdbfe; border-left-color:#2563eb; }} .alert-warning {{ background:#fffbeb; border-color:#fde68a; border-left-color:#d39a19; }} .alert-error {{ background:#fff1f2; border-color:#fecdd3; border-left-color:#c93c47; }}
.badge {{ display:inline-block; padding:.2rem .55rem; border-radius:999px; font-size:.7rem; font-weight:700; letter-spacing:.03em; }} .badge-muted,.missing-value {{ color:#8b95a1; background:#f8fafc; border:1px dashed #cbd5df; }} .sev {{ display:inline-block; padding:.2rem .55rem; border-radius:999px; font-size:.72rem; font-weight:700; }}
.kpi-label {{ color:var(--muted); font-size:.75rem; font-weight:600; }} .editing-banner {{ padding:.55rem .75rem; border-left:3px solid var(--brand); background:#f2f9e8; color:#4f670e; border-radius:6px; font-size:.8rem; margin-bottom:.8rem; }} .source-chip {{ font-family:ui-monospace,SFMono-Regular,monospace; font-size:.72rem; color:#536171; background:#f4f6f8; padding:.2rem .4rem; border-radius:4px; overflow-wrap:anywhere; }}
.incident-card {{ border-left:4px solid var(--brand); min-height:0!important; }} .incident-card.untitled {{ border-left-style:dashed; border-left-color:#aab4bf; background:#fbfcfd; }} .incident-card-title {{ font-size:.78rem!important; line-height:1.2; font-weight:700; margin:.15rem 0 .25rem; }} .incident-card-description {{ min-height:1.2rem; color:#4b5563; font-size:.78rem; line-height:1.3; }} .card-preview {{ position:relative; height:120px; overflow:hidden; border-radius:8px; background:#eef2f5; margin:.45rem 0; }} .card-preview-poster {{ height:100%; display:flex; align-items:center; justify-content:center; color:#8793a0; font-size:.76rem; }} .queue-item {{ border-bottom:1px solid #edf0f3; padding:.5rem 0; }} .queue-item:last-child {{ border-bottom:0; }} .queue-link {{ display:block; width:100%; border-radius:8px; padding:.45rem .55rem; color:#4f8100!important; font-weight:600; text-decoration:none!important; }} .queue-link:hover {{ background:#f2f9e8; }} .missing-value {{ display:inline-block; padding:.16rem .45rem; border-radius:5px; font-style:italic; font-size:.78rem; }} code,.stCode {{ color:#536171!important; }}
</style>
"""


def apply_base_style() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", metadata: str = "") -> None:
    suffix = f" · {html.escape(subtitle)}" if subtitle else ""
    meta = f'<div class="meta-line">{html.escape(metadata)}</div>' if metadata else ""
    st.markdown(
        f'<div class="rise-header"><div><span class="wordmark">RISE UP</span><span class="nvidia-pill">NVIDIA POWERED</span></div><div class="tagline">{html.escape(title)}{suffix}</div>{meta}</div>',
        unsafe_allow_html=True,
    )


def alert(message: str, kind: str = "info", icon: str = "ⓘ") -> None:
    st.markdown(
        f'<div class="alert alert-{kind}"><span>{icon}</span><div>{message}</div></div>', unsafe_allow_html=True
    )


def status_badge(status: str) -> str:
    value = html.escape(status or "Not supplied")
    return f'<span class="badge {"badge-muted" if not status else ""}">{value}</span>'


def severity_badge(severity: int | None) -> str:
    try:
        value = max(1, min(5, int(severity)))
    except (TypeError, ValueError):
        return '<span class="badge badge-muted">Not supplied</span>'
    color = SEVERITY_COLORS[value]
    return f'<span class="sev" style="background:{color}1f;color:{color};border:1px solid {color}55">{value}/5 · {SEVERITY_LABELS[value]}</span>'


def missing_value(label: str = "Not supplied") -> str:
    return f'<span class="missing-value">{html.escape(label)}</span>'
