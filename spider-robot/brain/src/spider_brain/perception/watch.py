"""Watch mode: while the owner has it on, look about every 0.6 s and turn held hand gestures into
allowed actions. Off by default and off again after watch_minutes. The only robot command sent
from here is Stop; everything else is speech or a photo to the owner.

Every frame is looked at once: a gesture must be seen in two different camera frames before it
acts. While the app's live view runs, watch mode reads its frames and asks for none of its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from ..robot_client import RobotClient, RobotOffline
from . import decode_jpeg
from .faces import FaceMatch

if TYPE_CHECKING:
    from ..mobile.camera import FrameFeed

log = logging.getLogger(__name__)

LATE_TICK_MS = 10.0  # half the 20 ms control budget
LATE_WINDOW = 8
LATE_COUNT = 3
FEED_MAX_AGE_S = 2.0
IDLE_S = 0.1  # how often to look again when there is no new frame yet


class Debouncer:
    """A gesture fires when seen in `need` of the last `window` frames, then not again until it
    has gone for a frame and its cooldown has passed. Holding a palm sends one Stop, not ten."""

    def __init__(self, need: int = 2, window: int = 3,
                 cooldown_s: dict[str, float] | None = None, default_cooldown_s: float = 6.0):
        self.need = need
        self.history: deque[set[str]] = deque(maxlen=window)
        self.cooldown_s = cooldown_s or {}
        self.default_cooldown_s = default_cooldown_s
        self.last_fired: dict[str, float] = {}
        self.held: set[str] = set()  # fired and not yet released

    def push(self, labels: set[str], now: float) -> list[str]:
        self.history.append(labels)
        self.held &= labels
        fired = []
        for label in sorted(labels):
            if label in self.held or sum(label in f for f in self.history) < self.need:
                continue
            wait = self.cooldown_s.get(label, self.default_cooldown_s)
            if now - self.last_fired.get(label, float("-inf")) < wait:
                continue
            self.last_fired[label] = now
            self.held.add(label)
            fired.append(label)
        return fired


class Watcher:
    def __init__(self, robot: RobotClient, perception, actions: dict[str, str],
                 anyone: set[str], say: Callable[[str], Awaitable[None]],
                 photo: Callable[[bytes, str], Awaitable[None]], period_s: float = 0.6,
                 minutes: float = 30.0, clock: Callable[[], float] = time.monotonic,
                 feed: FrameFeed | None = None) -> None:
        self.robot, self.perception = robot, perception
        self.actions, self.anyone = actions, anyone
        self.say, self.photo = say, photo
        self.period_s, self.minutes, self.clock = period_s, minutes, clock
        self.feed = feed
        stop_labels = {g: 1.0 for g, a in actions.items() if a == "stop"}
        self.debounce = Debouncer(cooldown_s=stop_labels)
        self.until = float("-inf")
        self._late: deque[bool] = deque(maxlen=LATE_WINDOW)
        self._late_ts: float | None = None
        self._last_feed_n: int | None = None  # the live-view frame looked at last

    @property
    def on(self) -> bool:
        return self.clock() < self.until

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.until - self.clock())

    def turn_on(self) -> None:
        self.until = self.clock() + self.minutes * 60.0

    def turn_off(self) -> None:
        self.until = float("-inf")

    def _control_late(self) -> bool:
        st = self.robot.state
        if st is not None and st.ts != self._late_ts:
            self._late_ts = st.ts
            self._late.append(st.loop_late_max_ms > LATE_TICK_MS)
        return sum(self._late) >= LATE_COUNT

    def effective_period_s(self) -> float:
        """Half rate when the control loop is late, like the app's live view."""
        return 2 * self.period_s if self._control_late() else self.period_s

    async def next_frame(self) -> bytes | None:
        """A camera frame not looked at before, or None when there is none yet."""
        feed = self.feed
        if feed is not None and feed.latest is not None:
            age = feed.age_s()
            if age is not None and age <= FEED_MAX_AGE_S:
                if feed.latest.n == self._last_feed_n:
                    return None  # already looked at; wait for the live view's next frame
                self._last_feed_n = feed.latest.n
                return feed.latest.jpeg
        if feed is not None and feed.wanted:
            return None  # the live view is fetching frames: do not compete with it
        if not self.robot.camera_free(human=False):
            return None  # a voice question or a photo is waiting for the camera: let it go first
        return await self.robot.snapshot(timeout_s=3.0)

    async def step(self) -> bool:
        """Look at one new frame and act on gestures held long enough. False: no new frame."""
        jpeg = await self.next_frame()
        if jpeg is None:
            return False
        frame = decode_jpeg(jpeg)
        seen = await self.perception.run(self.perception.see, frame)
        by_label = {g.label: g for g in seen.gestures}
        for label in self.debounce.push(set(by_label), self.clock()):
            await self.act(label, by_label[label].person, jpeg, frame)
        return True

    async def act(self, label: str, person: FaceMatch | None, jpeg: bytes, frame) -> None:
        action = self.actions.get(label)
        if action is None:
            return
        known = person is not None and person.person_id is not None
        if not known and action not in self.anyone:
            log.info("gesture %s from someone not enrolled: ignored", label)
            return
        name = person.spoken if known else ""
        log.info("gesture %s -> %s (%s)", label, action, person.person_id if known else "?")
        if action == "stop":
            self.robot.stop()
        elif action == "greet":
            await self.say(f"أهلين {name}" if name else "أهلين")
        elif action == "photo":
            await self.photo(jpeg, f"gesture {label}"
                             + (f" by {person.person_id}" if known else ""))
        elif action == "describe":
            await self.say(await self.perception.run(self.perception.describe, frame))
        elif action.startswith("say:"):
            await self.say(action[4:])

    async def run(self) -> None:
        while True:
            started = self.clock()
            looked = False
            if self.on:
                try:
                    looked = await self.step()
                except RobotOffline:
                    await asyncio.sleep(1.0)
                except (TimeoutError, RuntimeError, ValueError) as exc:
                    log.debug("watch frame skipped: %r", exc)
                except Exception:
                    log.exception("watch step failed")
            period = self.effective_period_s() if looked else IDLE_S
            await asyncio.sleep(max(IDLE_S, period - (self.clock() - started)))


__all__ = ["Debouncer", "Watcher"]
