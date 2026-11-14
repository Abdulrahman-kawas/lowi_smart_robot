"""Live view from the existing snapshot path. No streaming, nothing new on the Pi.

One frame at a time on the remote source, through RobotClient's camera gate: at most one request
per CAMERA_GAP_S (0.6 s), and only when no photo or confirmation frame is waiting, so the live
view can never get a release refused for the gateway's rate limit.

Frames carry no capture time and the three machines' clocks differ, so a frame is stamped with
the brain's monotonic time of its request. It cannot have been taken earlier, so its age is an
upper bound.

The body takes snapshots in a thread of its own process unless the camera is external. If the
robot keeps reporting late control ticks while the live view runs, the feed halves its rate for a
while. One late tick is not enough: without real-time scheduling (the simulator) single spikes
are normal and have nothing to do with the camera.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from ..robot_client import CAMERA_GAP_S, RobotClient, RobotOffline

log = logging.getLogger(__name__)

FRAME_TIMEOUT_S = 2.5
LATE_TICK_MS = 10.0  # half the 20 ms control budget
LATE_WINDOW = 8  # robot states looked at (2 s at 4 Hz)
LATE_COUNT = 3  # late states among them that slow the live view down
SLOW_FOR_S = 10.0
SLOW_GAP_S = 2 * CAMERA_GAP_S
IDLE_POLL_S = 0.05


@dataclass(frozen=True)
class Frame:
    n: int
    jpeg: bytes
    asked_at: float  # monotonic; the frame is at most now - asked_at old


class FrameFeed:
    def __init__(
        self, robot: RobotClient, on_frame: Callable[[Frame], None],
        notify: Callable[[str, str], None], clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.robot, self.on_frame, self.notify, self.clock = robot, on_frame, notify, clock
        self.wanted = False
        self.latest: Frame | None = None
        self.rtt_ms: float | None = None
        self._n = 0
        self._slow_until = -math.inf
        self._failing = False
        self._late: deque[bool] = deque(maxlen=LATE_WINDOW)
        self._late_ts: float | None = None

    def age_s(self) -> float | None:
        return None if self.latest is None else self.clock() - self.latest.asked_at

    def control_loop_late(self) -> bool:
        """Several of the robot's recent states report a control tick that started late."""
        st = self.robot.state
        if st is not None and st.ts != self._late_ts:
            self._late_ts = st.ts
            self._late.append(st.loop_late_max_ms > LATE_TICK_MS)
        return sum(self._late) >= LATE_COUNT

    def _due(self, now: float) -> bool:
        late = self.control_loop_late()
        if not self.wanted or not self.robot.camera_free():
            return False
        if late:
            if now >= self._slow_until:
                self.notify("video_slowed", "the robot's control loop is running late; "
                            "live view at half rate")
            self._slow_until = now + SLOW_FOR_S
        if now < self._slow_until and self.latest is not None:
            return now - self.latest.asked_at >= SLOW_GAP_S
        return True

    async def run(self) -> None:
        while True:
            if not self._due(self.clock()):
                await asyncio.sleep(IDLE_POLL_S)
                continue
            try:
                jpeg, asked_at = await self.robot.snapshot_timed(FRAME_TIMEOUT_S, human=True)
            except RobotOffline:
                await asyncio.sleep(0.5)
                continue
            except (TimeoutError, RuntimeError) as exc:
                if not self._failing:
                    self._failing = True
                    self.notify("video_failed", f"no camera frame: {exc or 'timed out'}")
                continue
            if self._failing:
                self._failing = False
                self.notify("video_ok", "camera frames are arriving again")
            self.rtt_ms = round((self.clock() - asked_at) * 1000.0, 1)
            self._n += 1
            self.latest = Frame(self._n, jpeg, asked_at)
            self.on_frame(self.latest)
