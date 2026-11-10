"""The voice loop's connection to the command gateway. Voice never talks to the body directly."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from collections.abc import Callable

from spider_common.link import Link
from spider_common.protocol import (
    AskReply,
    Command,
    EStop,
    Heartbeat,
    Move,
    RobotEvent,
    RobotState,
    Stop,
    Topics,
)

from .rpc import RpcClient

log = logging.getLogger(__name__)
STATE_FRESH_S = 1.0
_MOTION_ENDED = frozenset({"obstacle_stop", "tilt", "fallen", "preempted", "estop"})


class GatewayClient:
    SOURCE = "voice"

    def __init__(
        self, link: Link, robot_id: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.link = link
        self.clock = clock
        self.rpc = RpcClient(link, robot_id)
        self._motion_until = 0.0
        self.topics = Topics(robot_id)
        self._cmd_topic = self.topics.request(self.SOURCE)
        self._event_topic = self.topics.source_event(self.SOURCE)
        self.session = uuid.uuid4().hex[:12]
        self._seq = itertools.count(1)
        self.state: RobotState | None = None
        self.state_rx: float | None = None
        self.last_event: RobotEvent | None = None

    @staticmethod
    def subscriptions(robot_id: str) -> list[str]:
        t = Topics(robot_id)
        return [t.source_event(GatewayClient.SOURCE), t.state, t.rpc_reply("ask", "voice"),
                t.rpc_reply("stt", "voice")]

    @property
    def walking(self) -> bool:
        """Moving as far as this process knows: a Move it just sent, or recent telemetry."""
        now = self.clock()
        if now < self._motion_until:
            return True
        if self.state is None or self.state_rx is None or now - self.state_rx > STATE_FRESH_S:
            return False
        return self.state.mode == "walking"

    def send(self, cmd: Command, trace: str = "", qos: int = 1) -> int:
        """Publish one command. Returns its seq, or -1 when the broker is unreachable."""
        seq = next(self._seq)
        out = cmd.model_copy(update={"seq": seq, "ts": time.time(), "session": self.session,
                                     "trace": trace})
        if isinstance(cmd, Move):
            self._motion_until = self.clock() + cmd.duration_s
        elif isinstance(cmd, (Stop, EStop)):
            self._motion_until = 0.0
        return seq if self.link.publish(self._cmd_topic, out.model_dump_json(), qos=qos) else -1

    def stop(self, trace: str = "") -> int:
        return self.send(Stop(), trace)

    def estop(self, trace: str = "") -> int:
        return self.send(EStop(), trace)

    async def heartbeat_loop(self, hz: float) -> None:
        while True:
            self.link.publish(self._cmd_topic, Heartbeat(ts=time.time()).model_dump_json())
            await asyncio.sleep(1.0 / hz)

    async def run(self) -> None:
        async for msg in self.link.messages():
            try:
                if msg.topic == self.topics.state:
                    self.state = RobotState.model_validate_json(msg.payload)
                    self.state_rx = self.clock()
                elif msg.topic == self._event_topic:
                    self._on_event(RobotEvent.model_validate_json(msg.payload))
                elif msg.topic in self.rpc.reply_topics():
                    self.rpc.on_reply(AskReply.model_validate_json(msg.payload).trace, msg.payload)
            except Exception:
                log.exception("bad message on %s", msg.topic)

    def _on_event(self, ev: RobotEvent) -> None:
        self.last_event = ev
        if ev.kind in _MOTION_ENDED:
            self._motion_until = 0.0
