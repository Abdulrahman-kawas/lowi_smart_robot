"""Request and reply over MQTT. The worker can run on any machine with a broker login."""

from __future__ import annotations

import asyncio

from spider_common.link import Link
from spider_common.protocol import Topics


class RpcClient:
    def __init__(self, link: Link, robot_id: str, client: str = "voice") -> None:
        self.link, self.client = link, client
        self.topics = Topics(robot_id)
        self._waiting: dict[str, asyncio.Future[bytes]] = {}

    def reply_topics(self, services: tuple[str, ...] = ("ask", "stt")) -> list[str]:
        return [self.topics.rpc_reply(s, self.client) for s in services]

    async def call(self, service: str, trace: str, payload: str, timeout_s: float) -> bytes:
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self._waiting[trace] = future
        try:
            if not self.link.publish(self.topics.rpc_request(service), payload, qos=1):
                raise ConnectionError("broker not connected")
            return await asyncio.wait_for(future, timeout_s)
        finally:
            self._waiting.pop(trace, None)

    def on_reply(self, trace: str, payload: bytes) -> None:
        future = self._waiting.get(trace)
        if future is not None and not future.done():
            future.set_result(payload)
