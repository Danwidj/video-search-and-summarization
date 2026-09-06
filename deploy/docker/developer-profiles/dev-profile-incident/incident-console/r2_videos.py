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


@st.cache_data(ttl=900, show_spinner=False)
def playback_url(key):
    return client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET"], "Key": key, "ResponseContentDisposition": "inline"},
        ExpiresIn=3600,
    )


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
