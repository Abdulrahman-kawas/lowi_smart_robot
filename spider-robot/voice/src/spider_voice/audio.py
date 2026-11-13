"""Microphone and speaker through arecord and aplay.

Separate processes on purpose: they keep PortAudio out of this process, cannot block the event
loop, and killing aplay is the fastest way to silence the robot when somebody says stop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import time
from collections.abc import AsyncIterator

import numpy as np

log = logging.getLogger(__name__)


def frame_rms(frame: bytes) -> float:
    samples = np.frombuffer(frame, dtype="<i2")
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))


def is_speech_frame(voiced: bool, rms: float, min_rms_dbfs: float) -> bool:
    """A frame counts only if the VAD says so and it is loud enough to be someone nearby."""
    return voiced and rms > 0.0 and 20.0 * math.log10(rms / 32768.0) >= min_rms_dbfs


class ArecordCapture:
    def __init__(self, device: str, sample_rate: int, frame_ms: int) -> None:
        self.device, self.sample_rate = device, sample_rate
        self.frame_bytes = sample_rate * frame_ms // 1000 * 2

    async def frames(self) -> AsyncIterator[bytes]:
        proc = await asyncio.create_subprocess_exec(
            "arecord", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
            "-r", str(self.sample_rate), "-c", "1",
            # ALSA's default period is often 125 ms, which would delay both ends of the VAD.
            "--period-time=20000", "--buffer-time=80000",
            stdout=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None
        try:
            while True:
                yield await proc.stdout.readexactly(self.frame_bytes)
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()


class AplayOutput:
    def __init__(self, device: str) -> None:
        self.device = device
        self._proc: asyncio.subprocess.Process | None = None
        self._cut = False

    def cut(self) -> None:
        self._cut = True
        if self._proc is not None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()

    async def play(self, chunks: AsyncIterator[bytes], sample_rate: int) -> float | None:
        self._cut = False
        started = time.perf_counter()
        first: float | None = None
        proc = await asyncio.create_subprocess_exec(
            "aplay", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
            "-r", str(sample_rate), "-c", "1",
            stdin=asyncio.subprocess.PIPE,
        )
        self._proc = proc
        assert proc.stdin is not None
        try:
            async for chunk in chunks:
                if self._cut:
                    return None
                proc.stdin.write(chunk)
                await proc.stdin.drain()
                if first is None:
                    first = time.perf_counter() - started
            proc.stdin.close()
            await proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            return None  # aplay was killed by cut()
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
            self._proc = None
        return None if self._cut else first
