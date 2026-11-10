"""Fresh frame, then an explicit yes. Shared by Telegram and the dashboard.

The gateway on the Pi enforces the rule; this module is only the human side of it. A confirmation
can be used once, and it dies with its challenge.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time

from .robot_client import Confirmation, ConfirmRefused, RobotClient, RobotOffline
from .supervision.events import EventBus

log = logging.getLogger(__name__)


class ConfirmFlow:
    def __init__(self, robot: RobotClient, bus: EventBus) -> None:
        self.robot, self.bus = robot, bus
        self._open: dict[str, tuple[Confirmation, str | None, float]] = {}
        self._tasks: set[asyncio.Task] = set()

    def needs_wake(self, posture: str) -> bool:
        if not self.robot.via_gateway or posture == "relax":
            return False
        st = self.robot.state
        return st is None or st.mode in ("relaxed", "fallen")

    async def begin(self, action: str, posture: str | None = None) -> Confirmation:
        try:
            conf = await self.robot.request_confirm(action)
        except RobotOffline as exc:
            raise ConfirmRefused(str(exc)) from exc
        self._open[conf.id] = (conf, posture, time.monotonic() + conf.ttl_s)
        self.bus.publish("confirm_request", id=conf.id, action=action, ttl_s=conf.ttl_s,
                         data=base64.b64encode(conf.jpeg).decode("ascii"))
        return conf

    def start(self, action: str, posture: str | None = None) -> None:
        """For callers that cannot wait, such as a websocket message."""

        async def run() -> None:
            try:
                await self.begin(action, posture)
            except ConfirmRefused as exc:
                self.bus.publish("message", text=f"Confirmation refused: {exc}")

        task = asyncio.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def resolve(self, challenge_id: str, approved: bool) -> bool:
        """Returns True if the challenge was still open."""
        entry = self._open.pop(challenge_id, None)
        if entry is None:
            return False
        conf, posture, expires = entry
        if time.monotonic() >= expires:
            return False
        if approved:
            if conf.action == "estop_release":
                self.robot.estop_release(conf)
            else:
                self.robot.posture_confirmed(posture or "stand", conf)
        return True
