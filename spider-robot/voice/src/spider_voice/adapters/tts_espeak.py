"""espeak-ng: robotic but instant and always available, the offline fallback."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from ..config import EspeakCfg


def strip_wav_header(data: bytes) -> bytes:
    """espeak-ng writes a RIFF header to stdout; aplay here receives raw PCM."""
    at = data.find(b"data", 0, 256)
    if data[:4] != b"RIFF" or at < 0:
        raise ValueError("espeak-ng did not produce WAV data")
    return data[at + 8:]


class EspeakTTS:
    def __init__(self, cfg: EspeakCfg) -> None:
        self.cfg = cfg
        self.sample_rate = cfg.sample_rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        proc = await asyncio.create_subprocess_exec(
            "espeak-ng", "-v", self.cfg.voice, "--stdout", text,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"espeak-ng exited with {proc.returncode}")
        yield strip_wav_header(out)
