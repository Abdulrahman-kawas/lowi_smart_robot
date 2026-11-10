"""The swappable parts. Moving a service to another machine is a config change.

Everything async here is cancellable and must honour its own timeout; nothing blocks the event
loop. Vendor SDKs live only in spider_voice.adapters and are imported inside the adapter.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Transcript:
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0


@dataclass(frozen=True)
class RouterDecision:
    act: str
    say: str


class STT(Protocol):
    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript: ...


class TTS(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """Raw 16-bit mono PCM chunks, as soon as each is ready."""
        ...


class Router(Protocol):
    async def route(
        self, transcript: str, on_act: Callable[[str], None] | None = None
    ) -> RouterDecision:
        """Decide. on_act, if given, is called once as soon as the act is readable in the stream."""
        ...


class Vision(Protocol):
    async def ask(self, question: str, trace: str) -> str:
        """The worker takes the photo itself, so no image crosses this interface."""
        ...


class Answerer(Protocol):
    """Slow path for a harder question. The answer is only ever spoken."""

    async def answer(self, question: str, trace: str) -> str: ...


class AudioOut(Protocol):
    async def play(self, chunks: AsyncIterator[bytes], sample_rate: int) -> float | None:
        """Play to the end. Returns the seconds until the first sample, or None if cut off."""
        ...

    def cut(self) -> None:
        """Stop the sound now (barge-in)."""
        ...
