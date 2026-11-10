"""The only process allowed to send commands to the robot body.

The body orders commands per session and accepts a heartbeat from anyone, which is right for one
brain and wrong for several. Voice on the Pi and the brain on the server therefore send to the
gateway, which:

  * renumbers everything into one session, so a Stop fences every earlier Move
  * lets a Stop or E-stop from any source through at once
  * gives motion to the highest-priority active source
  * tracks each source's heartbeat: if the source that owns the motion goes quiet the robot stops,
    while the other sources keep working
  * returns each source its events with its own seq numbers

It adds to the body's limits and replaces none of them. If the gateway dies, its heartbeat stops
and the body's own watchdog stops the robot.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable

from pydantic import ValidationError
from spider_common.link import Link, topic_matches
from spider_common.protocol import (
    BodyPose,
    Command,
    EStop,
    EStopRelease,
    EventKind,
    Heartbeat,
    Move,
    Posture,
    RobotEvent,
    Stop,
    Topics,
    parse_command,
)

log = logging.getLogger(__name__)

PRIORITY = {"voice": 2, "remote": 1, "planner": 0}
POSE_HOLD_S = 2.0  # how long a posture change keeps lower-priority sources out
MAX_TRACKED = 1024  # commands remembered for translating event seq numbers
_SOURCE_ONLY: frozenset[EventKind] = frozenset({"ack", "rejected", "move_done", "snapshot_failed"})


class Gateway:
    def __init__(
        self,
        link: Link,
        robot_id: str,
        source_timeout_s: float = 1.5,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.link = link
        self.robot_id = robot_id
        self.topics = Topics(robot_id)
        self.source_timeout_s = source_timeout_s
        self.clock = clock
        self.wall = wall
        self.session = uuid.uuid4().hex[:12]
        self._seq = itertools.count(1)
        self._origin: OrderedDict[int, tuple[str, int]] = OrderedDict()
        self._seen: dict[str, float] = {}
        self._owner: str | None = None
        self._owner_until = 0.0
        self._fence: dict[tuple[str, str], int] = {}  # (source, session) -> seq of its last Stop
        self._stop_ts = 0.0
        self._stop_source: str | None = None

    @staticmethod
    def subscriptions(robot_id: str) -> list[str]:
        t = Topics(robot_id)
        return [t.request_filter, t.event]

    # ------------------------------------------------------------------ requests
    def on_request(self, source: str, payload: bytes | str) -> None:
        if source not in PRIORITY:
            log.warning("ignoring command from unknown source %r", source)
            return
        now = self.clock()
        self._seen[source] = now
        try:
            cmd = parse_command(payload)
        except ValidationError as exc:
            self._reply(source, None, "rejected", f"invalid command ({exc.error_count()} errors)")
            return
        if isinstance(cmd, Heartbeat):
            return
        if isinstance(cmd, (Stop, EStop)):
            key = (source, cmd.session)
            self._fence[key] = max(self._fence.get(key, -1), cmd.seq)
            self._record_stop(source, cmd.ts)
            self._owner = None
            self._forward(cmd, source)
            return
        if isinstance(cmd, EStopRelease) and source == "planner":
            self._reply(source, cmd.seq, "rejected", "the planner may not release an E-stop")
            return
        if isinstance(cmd, Move):
            if cmd.seq <= self._fence.get((source, cmd.session), -1):
                return  # sent before this source's own Stop: drop silently, as the body does
            if source != self._stop_source and cmd.ts < self._stop_ts:
                self._reply(source, cmd.seq, "rejected", "sent before a newer stop")
                return
        if isinstance(cmd, (Move, Posture, BodyPose)) and not self._claim(source, cmd, now):
            self._reply(source, cmd.seq, "rejected", f"busy: {self._owner} is in control")
            return
        self._forward(cmd, source)

    def _claim(self, source: str, cmd: Move | Posture | BodyPose, now: float) -> bool:
        owner_active = self._owner is not None and now < self._owner_until
        if owner_active and PRIORITY[source] < PRIORITY[self._owner]:
            return False
        self._owner = source
        self._owner_until = now + (cmd.duration_s if isinstance(cmd, Move) else POSE_HOLD_S)
        return True

    def _record_stop(self, source: str, ts: float) -> None:
        # A sender whose clock runs ahead must not block everyone else's motion.
        self._stop_ts = max(self._stop_ts, min(ts, self.wall()))
        self._stop_source = source

    def _forward(self, cmd: Command, source: str | None) -> None:
        out = next(self._seq)
        if source is not None:
            self._origin[out] = (source, cmd.seq)
            while len(self._origin) > MAX_TRACKED:
                self._origin.popitem(last=False)
        renumbered = cmd.model_copy(update={"seq": out, "session": self.session})
        qos = 0 if isinstance(cmd, Move) else 1
        if not self.link.publish(self.topics.cmd, renumbered.model_dump_json(), qos=qos):
            log.warning("could not send %s to the body", cmd.type)
            if source is not None:
                self._reply(source, cmd.seq, "rejected", "gateway is not connected to the body")

    # ------------------------------------------------------------------ events
    def on_event(self, payload: bytes | str) -> None:
        ev = RobotEvent.model_validate_json(payload)
        origin = self._origin.get(ev.seq) if ev.seq is not None else None
        if ev.kind in _SOURCE_ONLY:
            if origin is not None:
                self._republish(ev, origin[0], origin[1])
            return
        for source in PRIORITY:  # safety events reach everyone
            own = origin is not None and origin[0] == source
            self._republish(ev, source, origin[1] if own else None)

    def _republish(self, ev: RobotEvent, source: str, seq: int | None) -> None:
        translated = ev.model_copy(update={"seq": seq})
        self.link.publish(self.topics.source_event(source), translated.model_dump_json(), qos=1)

    def _reply(self, source: str, seq: int | None, kind: EventKind, detail: str) -> None:
        ev = RobotEvent(robot_id=self.robot_id, kind=kind, seq=seq, detail=detail)
        self.link.publish(self.topics.source_event(source), ev.model_dump_json(), qos=1)

    # ------------------------------------------------------------------ watchdog
    def _alive(self, source: str, now: float) -> bool:
        seen = self._seen.get(source)
        return seen is not None and now - seen <= self.source_timeout_s

    def tick(self) -> None:
        now = self.clock()
        if self._owner is not None:
            if not self._alive(self._owner, now):
                self._halt_lost_owner()
            elif now >= self._owner_until:
                self._owner = None
        if any(self._alive(source, now) for source in PRIORITY):
            beat = Heartbeat(ts=self.wall(), session=self.session)
            self.link.publish(self.topics.cmd, beat.model_dump_json())

    def _halt_lost_owner(self) -> None:
        lost, self._owner = self._owner, None
        log.warning("source %s went quiet while in control; stopping", lost)
        stop = Stop(ts=self.wall())
        self._record_stop("gateway", stop.ts)
        self._forward(stop, None)
        self._reply(lost, None, "link_lost", "no heartbeat from this source; robot stopped")

    # ------------------------------------------------------------------ run
    async def _pump(self) -> None:
        async for msg in self.link.messages():
            try:
                if msg.topic == self.topics.event:
                    self.on_event(msg.payload)
                elif topic_matches(self.topics.request_filter, msg.topic):
                    self.on_request(msg.topic.split("/")[-2], msg.payload)
            except Exception:
                log.exception("bad message on %s", msg.topic)

    async def _ticker(self, period_s: float) -> None:
        while True:
            self.tick()
            await asyncio.sleep(period_s)

    async def run(self, tick_hz: float = 4.0) -> None:
        await asyncio.gather(self._pump(), self._ticker(1.0 / tick_hz))
