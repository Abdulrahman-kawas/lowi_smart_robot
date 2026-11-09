"""WhatsApp alerts through the JobHunt repo's local voice-agent bridge.

The bridge (whatsapp-web.js, owner's SECONDARY number) listens on 127.0.0.1:3050 and accepts
POST /send-voice-alert {"text_caption": "..."} with the header X-Bridge-Token. It only exists on
the owner's own machine, so this works when the brain runs locally (phase 2) — on EC2 leave
whatsapp_bridge_url empty. Volume is kept low (a cooldown per alert kind): an unofficial
WhatsApp automation can get the number banned.
"""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)


class WhatsAppNotifier:
    def __init__(self, base_url: str, token: str, cooldown_s: float = 300.0,
                 http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(base_url=base_url, timeout=15.0)
        self.token = token
        self.cooldown_s = cooldown_s
        self._last: dict[str, float] = {}

    async def alert(self, text: str, kind: str = "info") -> bool:
        now = time.monotonic()
        if now - self._last.get(kind, -1e9) < self.cooldown_s:
            return False
        self._last[kind] = now
        try:
            resp = await self.http.post(
                "/send-voice-alert",
                json={"text_caption": text[:4000]},
                headers={"X-Bridge-Token": self.token},
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPError as exc:  # alerts are best effort; never break the brain
            log.warning("WhatsApp alert failed: %s", exc)
            return False
