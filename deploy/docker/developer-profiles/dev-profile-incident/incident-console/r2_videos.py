"""Read-only R2 video catalog and short-lived playback links. No incident storage."""

import os
from pathlib import PurePosixPath

import boto3
import streamlit as st
from botocore.config import Config

import config  # noqa: F401 — loads the app environment before reading R2 settings.

# Demo-only category aliases; never presented as the actual incident evidence.
CATEGORY_ALIASES = {
    "animal": ("animal", "animals"),
    "fighting": ("fighting", "fight", "shooting", "abuse", "assault"),
    "explosion": ("explosion", "explosions", "shooting"),
    "burglary": ("burglary", "robbery", "stealing"),
    "road accident": ("roadaccident", "roadaccidents", "accident", "accidents"),
}


def configured():
    return all(os.getenv(key) for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET"))


def client():
    return boto3.client(
        "s3",
        endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", connect_timeout=10, read_timeout=20, retries={"max_attempts": 2}),
    )


@st.cache_data(ttl=300, show_spinner=False)
def list_video_keys():
    keys = []
    for page in client().get_paginator("list_objects_v2").paginate(Bucket=os.environ["R2_BUCKET"]):
        keys.extend(
            obj["Key"] for obj in page.get("Contents", []) if obj["Key"].lower().endswith((".mp4", ".webm", ".mov"))
        )
    return sorted(keys)


def category_matches(category, keys):
    if not category:
        return []
    aliases = CATEGORY_ALIASES.get(category, (category,))

    def clean(value):
        return "".join(c for c in value.lower() if c.isalpha())

    # Prefer the exact category; use a related category only if it has no clips.
    for alias in aliases:
        matches = []
        for key in keys:
            parts = PurePosixPath(key).parts
            if any(clean(part) == alias for part in parts[:-1]) or clean(PurePosixPath(key).stem).startswith(alias):
                matches.append(key)
        if matches:
            return sorted(matches)
    return []


def map_incidents_to_video_keys(incidents, keys):
    """Assign one distinct R2 object to each incident.

    Existing filenames win when the object exists. Rows with no matching object
    use the next unused object in the same category, so every report still has a
    real, stable video without pretending that the demo clip is its ground truth.
    """
    by_filename = {PurePosixPath(key).name: key for key in keys}
    assignments = {}
    used = set()
    for incident in incidents:
        exact = by_filename.get(incident.get("Filename"))
        if exact and exact not in used:
            assignments[incident["Incident_ID"]] = exact
            used.add(exact)
    for incident in incidents:
        incident_id = incident["Incident_ID"]
        if incident_id in assignments:
            continue
        candidates = [key for key in category_matches(incident.get("Type"), keys) if key not in used]
        if not candidates:
            # A category may have fewer source clips than fixture rows (the
            # current R2 bucket has 15 animal clips and 20 animal incidents).
            # Use a distinct bucket clip rather than showing the same video for
            # multiple reports; the UI exposes the source filename clearly.
            candidates = [key for key in keys if key not in used]
        if candidates:
            assignments[incident_id] = candidates[0]
            used.add(candidates[0])
    return assignments


@st.cache_data(ttl=900, show_spinner=False)
def playback_url(key):
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": key, "ResponseContentDisposition": "inline"},
        ExpiresIn=3600,
    )


# Screenshots for entities / instruments / assets are ordinary objects in the
# same bucket; a presigned inline GET is all the detail view needs.
image_url = playback_url


def top_level_prefixes(keys):
    """Distinct ``anomaly/<cat>/`` / ``normal_videos/`` prefixes across the bucket."""
    prefixes = set()
    for key in keys:
        parts = PurePosixPath(key).parts
        prefixes.add("/".join(parts[:2]) + "/" if len(parts) > 2 else f"{parts[0]}/" if len(parts) > 1 else "")
    return sorted(p for p in prefixes if p)


def filter_keys(keys, *, prefix=None, query=None):
    """Narrow the bucket listing for the manual video picker."""
    result = keys
    if prefix and prefix != "All":
        result = [k for k in result if k.startswith(prefix)]
    if query:
        needle = query.casefold()
        result = [k for k in result if needle in k.casefold()]
    return result


def demo_video(report):
    """Render a category-matched demo source picker and return a playable video."""
    if not configured():
        return {}
    try:
        with st.spinner("Finding category-matched R2 footage…"):
            matches = category_matches(report["incident_type"], list_video_keys())
        if not matches:
            st.info("No R2 footage matches this category. You can link a video manually below.")
            return {}
        # Distribute demo incidents over matching footage deterministically.
        index = sum(ord(char) for char in str(report["id"])) % len(matches)
        key = st.selectbox("Cloudflare R2 demo footage", matches, index=index, key=f"r2_demo_{report['id']}")
        st.caption(
            "Category-matched demo footage — not the actual event described in this sample report. Sample timestamps may refer to a different moment."
        )
        return {"Filepath": playback_url(key), "filename": key}
    except Exception:
        st.warning("R2 footage could not be loaded. Check the connection or link a video manually below.")
        return {}
