"""In-memory application state for the base-profile mock.

Everything here resets on process restart by design: this mock is a local
development aid, not a persistence layer. A single `AppState` singleton is
injected into routes via FastAPI `Depends(get_state)`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import hashlib
import time


@dataclass
class UploadInProgress:
    """Tracks chunk assembly for one `nvstreamer-identifier` upload."""

    identifier: str
    filename: str
    chunks_received: int = 0
    total_chunks: int = 1
    bytes_received: int = 0
    sensor_id: str = ""


@dataclass
class Stream:
    """One completed upload / RTSP stream, keyed by sensor/stream id."""

    stream_id: str
    name: str
    filename: str
    bytes_total: int
    created_at: float = field(default_factory=time.time)
    stream_type: str = "file"  # "file" (uploaded video) or "rtsp"


@dataclass
class ConversationTurn:
    role: str
    text: str


@dataclass
class HitlThread:
    """Ephemeral HITL round-trip state, alive only for the life of one websocket connection."""

    thread_id: str
    conversation_id: str
    parent_id: str
    reply_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    edit_count: int = 0


class AppState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.uploads: dict[str, UploadInProgress] = {}
        self.streams: dict[str, Stream] = {}
        self.conversations: dict[str, list[ConversationTurn]] = {}
        self.hitl_threads: dict[str, HitlThread] = {}
        self.static_files: dict[str, bytes] = {}

    @staticmethod
    def derive_sensor_id(identifier: str) -> str:
        """Deterministic sensor_id for a given nvstreamer identifier.

        Repeated chunk POSTs for the same upload must always resolve to the
        same sensor id, and the result must satisfy the agent's
        ``^[A-Za-z0-9._-]{1,128}$`` sensor_id validation.
        """
        digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16]
        return f"sensor-{digest}"


_state = AppState()


def get_state() -> AppState:
    return _state
