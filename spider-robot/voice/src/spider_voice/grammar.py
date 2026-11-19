"""The closed-vocabulary motion grammar and the wake-word gate.

Common commands are matched on the transcript in microseconds, without a model. The same lexicon
checks anything the LLM router proposes: the router may only choose a motion whose words the owner
actually said, so a hallucination or an injected instruction cannot invent a walk.

Expressive moves (dance, wave, ...) come only from this grammar. They are not router acts at all,
so the router cannot propose one, and cross_check refuses them like any motion. An entry of
several words is a phrase: its words must follow each other, and they are not matched again as
single words ("سلم علي" is offer_hand, not wave).
"""

from __future__ import annotations

from dataclasses import dataclass

from .text import tokens, word_matches

MOTION_ACTS = frozenset({"forward", "back", "left", "right"})
MOVE_ACTS = frozenset({
    "dance", "wave", "bow", "reach", "attack_stance", "defense_stance", "alert", "sleep",
    "celebrate", "hi", "offer_hand",
})
LOOK_ACTS = frozenset({"look_left", "look_right", "look_center"})
ROUTER_ACTS = ("forward", "back", "left", "right", "stop", "look", "none")

LEXICON: dict[str, tuple[str, ...]] = {
    "forward": ("قدام", "امام", "لقدام", "للامام", "امشي", "تقدم", "forward", "ahead"),
    "back": ("ورا", "وراء", "لورا", "خلف", "للخلف", "ارجع", "back", "backward"),
    "left": ("يسار", "شمال", "لليسار", "للشمال", "left"),
    "right": ("يمين", "لليمين", "right"),
    "stand": ("قوم", "انهض", "stand"),
    "sit": ("اقعد", "اجلس", "sit"),
    "look": ("شوف", "انظر", "بص", "look", "see"),
    "look_left": ("شوف يسار", "شوف شمال", "شوف لليسار", "شوف عاليسار", "انظر يسار",
                  "بص يسار", "look left"),
    "look_right": ("شوف يمين", "شوف لليمين", "شوف عاليمين", "انظر يمين", "بص يمين",
                   "look right"),
    "look_center": ("شوف قدام", "شوف لقدام", "انظر قدام", "بص قدام", "look ahead"),
    "dance": ("ارقص", "dance"),
    "wave": ("سلّم", "باي"),
    "bow": ("انحني",),
    "reach": ("المس",),
    "attack_stance": ("وضع الهجوم",),
    "defense_stance": ("دافع", "وضع الدفاع"),
    "alert": ("انتبه",),
    "sleep": ("نام",),
    "celebrate": ("احتفل",),
    "hi": ("مرحبا", "هاي", "اهلا"),
    "offer_hand": ("سلم علي", "صافحني", "مد ايدك"),
}
NEGATIONS = frozenset(tokens("لا ما مش مو بلاش dont not"))
CANNED_SAY = {
    "forward": "حاضر، لقدام",
    "back": "حاضر، لورا",
    "left": "حاضر، يسار",
    "right": "حاضر، يمين",
    "stand": "حاضر",
    "sit": "حاضر",
    "look": "لحظة أشوف",
    "look_left": "أكيد",
    "look_right": "أكيد",
    "look_center": "أكيد",
    # never a word of the lexicon or a stop word: the robot must not command itself
    "dance": "يلا",
    "wave": "مع السلامة",
    "bow": "تفضلوا",
    "reach": "ثواني",
    "attack_stance": "جاهز",
    "defense_stance": "بحمي حالي",
    "alert": "عيني مفتوحة",
    "sleep": "تصبح على خير",
    "celebrate": "هيييه",
    "hi": "أهلين",
    "offer_hand": "تشرفنا",
}


@dataclass(frozen=True)
class GrammarHit:
    act: str
    say: str


# (act, entry tokens), phrases first so that they claim their words before single words do
_ENTRIES = sorted(
    ((act, tuple(tokens(entry))) for act, words in LEXICON.items() for entry in words),
    key=lambda e: -len(e[1]),
)


def acts_in(transcript: str) -> set[str]:
    """Every act whose words appear in the transcript."""
    words = tokens(transcript)
    used = [False] * len(words)
    found: set[str] = set()
    for act, entry in _ENTRIES:
        n = len(entry)
        for i in range(len(words) - n + 1):
            span = range(i, i + n)
            if n > 1 and any(used[k] for k in span):
                continue
            if n == 1 and used[i]:
                continue
            if all(word_matches(words[k], t) for k, t in zip(span, entry, strict=True)):
                found.add(act)
                if n > 1:
                    for k in span:
                        used[k] = True
    return found


def has_negation(transcript: str) -> bool:
    return any(word in NEGATIONS for word in tokens(transcript))


def match(transcript: str, max_words: int = 6) -> GrammarHit | None:
    """A hit only for a short utterance naming exactly one act; anything else goes to the router."""
    if len(tokens(transcript)) > max_words or has_negation(transcript):
        return None
    found = acts_in(transcript)
    if len(found) != 1:
        return None
    act = next(iter(found))
    return GrammarHit(act, CANNED_SAY[act])


class WakeGate:
    """Motion needs the wake word, or a recent command. Stop words never pass through here."""

    def __init__(self, words: tuple[str, ...], window_s: float, enabled: bool = True) -> None:
        self.words = tuple(t for w in words for t in tokens(w))
        self.window_s = window_s
        self.enabled = enabled
        self._open_until = -1.0

    def heard_wake_word(self, transcript: str) -> bool:
        return any(word_matches(w, t) for w in tokens(transcript) for t in self.words)

    def accept(self, transcript: str, now: float) -> bool:
        if not self.enabled:
            return True
        if self.heard_wake_word(transcript):
            self._open_until = now + self.window_s
            return True
        return now < self._open_until

    def extend(self, now: float) -> None:
        if self._open_until >= now:
            self._open_until = now + self.window_s

    def remove_from(self, transcript: str) -> str:
        """Drop the wake word so that 'يا لوي امشي قدام' routes the same as 'امشي قدام'."""
        words = transcript.split()
        keep = [not any(word_matches(w, t) for t in self.words) for w in tokens(transcript)]
        for i in range(1, len(keep)):
            if not keep[i] and tokens(words[i - 1]) == ["يا"]:  # the vocative goes with the name
                keep[i - 1] = False
        return " ".join(w for w, k in zip(words, keep, strict=False) if k)
