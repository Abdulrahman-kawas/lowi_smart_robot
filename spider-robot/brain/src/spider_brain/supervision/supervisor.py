"""The control surface the owner drives from the dashboard.

The graph nodes call ``gate_point`` (honours pause/stop) and ``request_approval`` (blocks on
a human decision). The dashboard calls ``pause`` / ``resume`` / ``stop`` / ``decide``.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Literal

from .events import EventBus

Status = Literal["running", "paused", "awaiting_approval", "stopping"]


class Stopped(Exception):
    """Raised inside a node when the owner pressed Stop."""


class Supervisor:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._resumed = asyncio.Event()
        self._resumed.set()  # not paused
        self._stop = asyncio.Event()
        self._approvals: dict[str, asyncio.Future[bool]] = {}
        self._ids = itertools.count(1)
        self.status: Status = "running"

    # -- owner controls -------------------------------------------------------
    def pause(self) -> None:
        self._resumed.clear()
        self.status = "paused"
        self.bus.publish("status", status="paused")

    def resume(self) -> None:
        self._resumed.set()
        self.status = "running"
        self.bus.publish("status", status="running")

    def stop(self) -> None:
        self._stop.set()
        self._resumed.set()  # unblock any pause wait so the Stopped check fires
        self.status = "stopping"
        self.bus.publish("status", status="stopping")
        for fut in list(self._approvals.values()):
            if not fut.done():
                fut.set_result(False)

    def decide(self, approval_id: str, approved: bool) -> None:
        fut = self._approvals.get(approval_id)
        if fut and not fut.done():
            fut.set_result(approved)

    @property
    def aborted(self) -> bool:
        return self._stop.is_set()

    # -- node-side hooks ------------------------------------------------------
    async def gate_point(self) -> None:
        """Block while paused; raise if stopped. Call at the top of every node."""
        if self._stop.is_set():
            raise Stopped()
        await self._resumed.wait()
        if self._stop.is_set():
            raise Stopped()

    async def request_approval(self, description: str, risk: str) -> bool:
        """Ask the owner to approve one action. Returns True to proceed, False to reject."""
        if self._stop.is_set():
            return False
        approval_id = f"a{next(self._ids)}"
        fut: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._approvals[approval_id] = fut
        self.status = "awaiting_approval"
        self.bus.publish(
            "approval_request", id=approval_id, description=description, risk=risk
        )
        try:
            approved = await fut
        finally:
            self._approvals.pop(approval_id, None)
        self.status = "running"
        self.bus.publish("approval_resolved", id=approval_id, approved=approved)
        return approved
