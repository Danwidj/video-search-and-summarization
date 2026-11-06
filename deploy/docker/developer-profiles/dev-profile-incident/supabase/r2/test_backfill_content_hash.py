# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for backfill_content_hash.py: `uv run --no-project --with pytest --with boto3 pytest`."""

import hashlib
import io

from backfill_content_hash import find_collisions, sha256_of_object


class Client:
    def __init__(self, objects):
        self.objects = objects

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            error = Exception("NoSuchKey")
            error.response = {"Error": {"Code": "NoSuchKey"}}
            raise error
        return {"Body": io.BytesIO(self.objects[Key])}


def test_hash_is_sha256_of_the_object_bytes():
    assert sha256_of_object(Client({"k": b"clip"}), "b", "k") == hashlib.sha256(b"clip").hexdigest()


def test_missing_object_is_none():
    assert sha256_of_object(Client({}), "b", "nope") is None


def test_collisions_name_every_video_sharing_a_hash():
    assert find_collisions({"a": "x", "b": "y", "c": "x"}) == {"x": ["a", "c"]}
    assert find_collisions({"a": "x", "b": "y"}) == {}
