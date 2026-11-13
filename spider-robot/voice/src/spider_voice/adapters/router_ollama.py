"""LFM2.5-350M (or any model) through Ollama's chat API: one JSON decision, streamed.

The act is reported the moment it is readable, so motion can start before the reply is finished.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable

import httpx

from ..config import RouterCfg
from ..grammar import ROUTER_ACTS
from ..interfaces import RouterDecision
from ..routing import NUM_CTX, NUM_PREDICT, SCHEMA, SYSTEM_PROMPT, TEMPERATURE, parse_decision

_EARLY_ACT = re.compile(r'"act"\s*:\s*"([a-z]+)"')


class OllamaRouter:
    def __init__(self, cfg: RouterCfg, http: httpx.AsyncClient | None = None) -> None:
        self.cfg = cfg
        self.http = http or httpx.AsyncClient(timeout=cfg.timeout_s)

    def payload(self, transcript: str) -> dict:
        return {
            "model": self.cfg.model,
            "stream": True,
            "format": SCHEMA,
            "keep_alive": -1,
            "options": {
                "temperature": TEMPERATURE,
                "top_k": 50,
                "repeat_penalty": 1.05,
                "num_predict": NUM_PREDICT,
                "num_ctx": NUM_CTX,
                "num_thread": 3,  # the three non-reserved cores
            },
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
        }

    async def _stream(self, transcript: str, on_act: Callable[[str], None] | None) -> str:
        buffer, fired = "", False
        url = f"{self.cfg.url.rstrip('/')}/api/chat"
        async with self.http.stream("POST", url, json=self.payload(transcript)) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                buffer += json.loads(line).get("message", {}).get("content", "")
                if not fired and (m := _EARLY_ACT.search(buffer)) and m.group(1) in ROUTER_ACTS:
                    fired = True
                    if on_act is not None:
                        on_act(m.group(1))
        return buffer

    async def route(
        self, transcript: str, on_act: Callable[[str], None] | None = None
    ) -> RouterDecision:
        raw = await asyncio.wait_for(self._stream(transcript, on_act), self.cfg.timeout_s)
        return parse_decision(raw)
