# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Placeholder evidence thumbnails: the crop_image_url of every mock search and chat hit points here."""

from __future__ import annotations

from importlib import resources

from fastapi import APIRouter
from fastapi.responses import Response

from base_profile_mock.finals_snapshot import EVIDENCE_IMAGE_ROUTE

router = APIRouter()

_PLACEHOLDER_BYTES = (resources.files("base_profile_mock") / "assets" / "placeholder.jpg").read_bytes()


@router.get(EVIDENCE_IMAGE_ROUTE + "/{image_path:path}")
def evidence_image(image_path: str) -> Response:  # noqa: ARG001 - the path only keeps each crop's URL distinct, the mock serves one image
    return Response(content=_PLACEHOLDER_BYTES, media_type="image/jpeg")
