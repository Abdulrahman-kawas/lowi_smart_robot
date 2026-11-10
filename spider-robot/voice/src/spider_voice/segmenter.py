"""Turns 20 ms microphone frames into utterances using a voice-activity decision per frame."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Utterance:
    pcm16: bytes
    duration_s: float
    peak_rms: float
    during_playback: bool  # any part of it overlapped the robot's own speech
    ended_at: float | None = None  # monotonic time of the end of speech; None skips the age check


class Segmenter:
    """The state machine is deterministic and has no I/O, so it is tested without a microphone."""

    def __init__(
        self,
        frame_ms: int = 20,
        start_frames: int = 6,  # 120 ms of speech before an utterance counts as started
        end_ms: int = 300,  # silence that ends an utterance
        preroll_ms: int = 200,  # audio kept from just before the start
        max_utterance_s: float = 8.0,
        min_utterance_ms: int = 200,
    ) -> None:
        self.frame_ms = frame_ms
        self.start_frames = start_frames
        self.end_frames = max(1, end_ms // frame_ms)
        self.max_frames = int(max_utterance_s * 1000 / frame_ms)
        self.min_frames = max(1, min_utterance_ms // frame_ms)
        self._pre: deque[bytes] = deque(maxlen=max(1, preroll_ms // frame_ms))
        self._frames: list[bytes] = []
        self._speech = 0
        self._silence = 0
        self._in_speech = False
        self._peak = 0.0
        self._overlap = False

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def _reset(self) -> None:
        self._frames = []
        self._speech = 0
        self._silence = 0
        self._in_speech = False
        self._peak = 0.0
        self._overlap = False

    def _finish(self) -> Utterance | None:
        voiced = len(self._frames) - self._silence
        frames, peak, overlap = self._frames, self._peak, self._overlap
        self._reset()
        if voiced < self.min_frames:
            return None
        return Utterance(b"".join(frames), len(frames) * self.frame_ms / 1000.0, peak, overlap)

    def push(self, frame: bytes, is_speech: bool, rms: float, playing: bool) -> Utterance | None:
        """Feed one frame. Returns a finished utterance, or None."""
        if not self._in_speech:
            if not is_speech:
                self._speech = 0
                self._pre.append(frame)
                return None
            self._speech += 1
            self._pre.append(frame)
            self._peak = max(self._peak, rms)
            self._overlap = self._overlap or playing
            if self._speech < self.start_frames:
                return None
            self._in_speech = True
            self._frames = list(self._pre)
            self._pre.clear()
            self._silence = 0
            return None
        self._frames.append(frame)
        self._peak = max(self._peak, rms)
        self._overlap = self._overlap or playing
        self._silence = 0 if is_speech else self._silence + 1
        if self._silence >= self.end_frames or len(self._frames) >= self.max_frames:
            return self._finish()
        return None
