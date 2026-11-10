"""Piper TTS. Synthesis runs on a worker thread and chunks are handed over as they are ready."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor

from ..config import PiperCfg


class PiperTTS:
    sample_rate = 16000  # ar_JO-kareem-low

    def __init__(self, cfg: PiperCfg, voice=None) -> None:
        self.cfg = cfg
        self._voice = voice
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

    def _load(self):
        if self._voice is None:
            from piper import PiperVoice

            self._voice = PiperVoice.load(self.cfg.model_path)
        return self._voice

    def preload(self) -> None:
        self._load()

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def work() -> None:
            try:
                for chunk in self._load().synthesize(text):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.audio_int16_bytes)
            except Exception as exc:  # handed to the consumer, who falls back to espeak-ng
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        self._pool.submit(work)
        while (item := await queue.get()) is not None:
            if isinstance(item, Exception):
                raise item
            yield item
