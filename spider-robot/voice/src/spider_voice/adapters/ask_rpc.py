"""Vision and hard questions, answered by the brain over MQTT.

AskReply has only text, so nothing that comes back through here can move the robot, and the Pi
holds no cloud keys and no model ports are opened on the server.
"""

from __future__ import annotations

from spider_common.protocol import MAX_ASK_CHARS, AskReply, AskRequest

from ..rpc import RpcClient


class RpcAsk:
    def __init__(self, rpc: RpcClient, timeout_s: float, need_image: bool) -> None:
        self.rpc, self.timeout_s, self.need_image = rpc, timeout_s, need_image

    async def _call(self, question: str, trace: str) -> str:
        request = AskRequest(trace=trace, text=question[:MAX_ASK_CHARS], need_image=self.need_image,
                             deadline_s=min(self.timeout_s, 120.0))
        raw = await self.rpc.call("ask", trace, request.model_dump_json(), self.timeout_s)
        reply = AskReply.model_validate_json(raw)
        if not reply.ok or not reply.text.strip():
            raise RuntimeError(reply.error or "no answer")
        return reply.text

    async def ask(self, question: str, trace: str) -> str:
        return await self._call(question, trace)

    async def answer(self, question: str, trace: str) -> str:
        return await self._call(question, trace)
