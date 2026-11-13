"""Stop words: the most important command never waits for a model.

The match runs directly on the transcript, without a wake word and without a confidence check. A
false positive only stops the robot, which is the safe direction, so this list favours recall.
"""

from __future__ import annotations

from dataclasses import dataclass

from .text import tokens, word_matches

DEFAULT_STOP_WORDS = (
    "وقف", "قف", "توقف", "اوقف", "ستوب", "stop", "halt", "خلاص", "بس", "كفايه",
)
DEFAULT_ESTOP_PHRASES = ("طوارئ", "emergency")


@dataclass(frozen=True)
class StopMatch:
    word: str
    emergency: bool


class StopWords:
    def __init__(
        self,
        words: tuple[str, ...] = DEFAULT_STOP_WORDS,
        emergency: tuple[str, ...] = DEFAULT_ESTOP_PHRASES,
    ) -> None:
        self.words = tuple(t for w in words for t in tokens(w))
        self.emergency = tuple(t for w in emergency for t in tokens(w))

    def match(self, transcript: str) -> StopMatch | None:
        found: StopMatch | None = None
        for word in tokens(transcript):
            for target in self.emergency:
                if word_matches(word, target):
                    return StopMatch(target, True)
            if found is None:
                for target in self.words:
                    if word_matches(word, target):
                        found = StopMatch(target, False)
                        break
        return found

    def strip_from(self, say: str) -> str:
        """Remove stop words from text the robot will speak, so it cannot stop itself."""
        kept = [
            original for original, word in zip(say.split(), tokens(say), strict=False)
            if not any(word_matches(word, t) for t in (*self.words, *self.emergency))
        ]
        return " ".join(kept)
