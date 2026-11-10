"""Arabic text normalisation for matching noisy transcripts against small word lists."""

from __future__ import annotations

import re
import unicodedata

_DIACRITICS = re.compile(r"[ً-ْٰـ]")  # harakat, dagger alef, tatweel
_NOT_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})


def normalize(text: str) -> str:
    """Lower case, no diacritics, Arabic letter variants folded, punctuation removed."""
    out = unicodedata.normalize("NFKC", text).lower()
    out = _DIACRITICS.sub("", out).translate(_FOLD)
    return " ".join(_NOT_WORD.sub(" ", out).split())


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def edit_distance_at_most_one(a: str, b: str) -> bool:
    """True when a and b differ by at most one insertion, deletion or substitution."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = j = 0
    edits = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        if la == lb:
            i += 1
        j += 1
    return edits + (lb - j) + (la - i) <= 1


def word_matches(word: str, target: str) -> bool:
    """Exact for short words, one edit allowed from four letters up: Whisper tiny is noisy."""
    if len(target) < 4:
        return word == target
    return edit_distance_at_most_one(word, target)
