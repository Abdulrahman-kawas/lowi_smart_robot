"""Keeps the robot from hearing itself, without an echo canceller.

The robot is half duplex. While it is talking, and for a short tail afterwards, what the microphone
hears is assumed to be its own voice unless it is clearly louder than the running level of its own
voice at the microphone. Those louder segments are barge-in candidates, and a barge-in candidate can
only do one thing: match a stop word. It never reaches the router, so the robot cannot answer or
obey itself.
"""

from __future__ import annotations

from dataclasses import dataclass


def db_ratio(db: float) -> float:
    return 10.0 ** (db / 20.0)


@dataclass
class EchoGate:
    tail_s: float = 0.25
    barge_in_margin_db: float = 9.0
    alpha: float = 0.05
    _playing: bool = False
    _ends_at: float = -1.0
    _echo_rms: float = 0.0

    def start_playback(self) -> None:
        self._playing = True

    def stop_playback(self, now: float) -> None:
        self._playing = False
        self._ends_at = now + self.tail_s

    def playing(self, now: float) -> bool:
        return self._playing or now < self._ends_at

    def observe_echo(self, rms: float) -> None:
        """Called for every frame during playback: how loud the robot is at its own microphone."""
        self._echo_rms += self.alpha * (rms - self._echo_rms)

    def is_barge_in(self, peak_rms: float) -> bool:
        return peak_rms >= self._echo_rms * db_ratio(self.barge_in_margin_db)
