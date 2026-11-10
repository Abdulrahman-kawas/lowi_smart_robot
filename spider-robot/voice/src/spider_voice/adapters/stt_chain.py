"""Server first, local if the server cannot answer. Selected with stt.primary: whisper_server.

Off by default. Decision 3 keeps Whisper tiny on the Pi as the primary; bench B-V1 decides whether
this swap is justified. The breaker in RpcStt keeps a dead server from costing a timeout each time.
"""

from __future__ import annotations

import logging

from ..interfaces import STT, Transcript

log = logging.getLogger(__name__)


class ServerFirstSTT:
    def __init__(self, server: STT, local: STT) -> None:
        self.server, self.local = server, local

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        try:
            return await self.server.transcribe(pcm16, sample_rate)
        except Exception as exc:
            log.info("server STT unavailable, using local: %r", exc)
        return await self.local.transcribe(pcm16, sample_rate)
