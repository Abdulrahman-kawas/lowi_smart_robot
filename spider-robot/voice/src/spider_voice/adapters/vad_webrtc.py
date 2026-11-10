"""webrtcvad: a per-frame speech decision in microseconds."""

from __future__ import annotations


class WebRtcVad:
    def __init__(self, aggressiveness: int, sample_rate: int) -> None:
        import webrtcvad

        self.sample_rate = sample_rate
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, self.sample_rate)
