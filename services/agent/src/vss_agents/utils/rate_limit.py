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

"""How long to wait after an HTTP 429 from the hosted service, shared by every stage of an analysis.

The main P1 call, the caption pass and the zoomed second look all wait the same way: the service's ``retry-after``
when it sent one, else a jittered exponential back-off, and only while the wait leaves the analysis budget (the
run's ``time.monotonic()`` deadline) at least :data:`MIN_CALL_SECONDS` for the call itself, so waiting can never carry
an analysis past the console's limit.
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
import math
import random
import time

BACKOFF_SECONDS = 5.0
BACKOFF_CAP_SECONDS = 30.0
MIN_CALL_SECONDS = 60.0
MAX_UNBOUNDED_WAIT_SECONDS = 120.0  # with no deadline (a batch evaluation)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a ``retry-after`` header (delta-seconds or an HTTP date); ``None`` when absent or unreadable."""
    if not value or not value.strip():
        return None
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            seconds = when.timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def backoff_seconds(retry_after: float | None, calls_made: int) -> float:
    """Seconds to wait after the ``calls_made``-th HTTP 429: its retry-after, else a jittered exponential back-off."""
    if retry_after is not None:
        return retry_after
    ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_SECONDS * 2 ** (calls_made - 1))
    return random.uniform(ceiling / 2, ceiling)


def wait_fits(wait: float, deadline: float | None) -> bool:
    """Whether waiting ``wait`` seconds still leaves ``MIN_CALL_SECONDS`` of the budget that ends at ``deadline``."""
    if deadline is None:
        return wait <= MAX_UNBOUNDED_WAIT_SECONDS
    return wait + MIN_CALL_SECONDS <= deadline - time.monotonic()
