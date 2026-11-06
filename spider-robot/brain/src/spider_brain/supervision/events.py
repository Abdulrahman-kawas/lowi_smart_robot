"""A tiny async pub/sub bus. The graph publishes events; dashboard websockets subscribe.

Each subscriber gets its own bounded queue. A slow/closed client is dropped rather than
blocking the agent. The most recent events are replayed to a client that connects late.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    def __init__(self, replay: int = 50) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=replay)

    def publish(self, kind: str, **data: Any) -> None:
        event = {"kind": kind, "ts": time.time(), **data}
        self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop the slowest event for this client; never block the agent loop.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        for event in self._history:
            q.put_nowait(event)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)
