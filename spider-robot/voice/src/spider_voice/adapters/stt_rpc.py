"""The bigger Whisper on the server, for utterances the local model was unsure about.

It travels over the broker, which is on the Pi, so a publish succeeds even when the server is gone.
Without the breaker every unsure utterance would wait out the full timeout.
"""

from __future__ import annotations

import base64
import math
import time
from collections.abc import Callable

from spider_common.obs import new_trace
from spider_common.protocol import SttReply, SttRequest

from ..interfaces import Transcript
from ..rpc import RpcClient


class ServerUnavailable(RuntimeError):
    pass


class RpcStt:
    def __init__(
        self, rpc: RpcClient, timeout_s: float, retry_after_s: float = 30.0, prompt: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rpc, self.timeout_s, self.retry_after_s = rpc, timeout_s, retry_after_s
        self.prompt, self.clock = prompt, clock
        self._closed_until = -math.inf

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        if self.clock() < self._closed_until:
            raise ServerUnavailable("server STT recently timed out; skipping it")
        trace = new_trace()
        request = SttRequest(trace=trace, audio_b64=base64.b64encode(pcm16).decode("ascii"),
                             rate=sample_rate, prompt=self.prompt)
        try:
            raw = await self.rpc.call("stt", trace, request.model_dump_json(), self.timeout_s)
        except TimeoutError:
            self._closed_until = self.clock() + self.retry_after_s
            raise
        reply = SttReply.model_validate_json(raw)
        if not reply.ok:
            raise RuntimeError(reply.error or "server STT failed")
        return Transcript(reply.text, avg_logprob=math.log(max(reply.confidence, 1e-6)))
