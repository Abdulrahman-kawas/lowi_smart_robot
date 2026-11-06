"""Long-term memory for the brain: small facts the owner wants kept across tasks.

Like the JobHunt agent's "memory first" rule: names of places ("the charging corner is left
of the sofa"), preferences ("speak Gulf Arabic", "never enter the bedroom"), corrections.
Stored as JSON lines in a local file (no PII beyond what the owner chooses to tell it).
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_FACTS = 500
MAX_FACT_CHARS = 500


@dataclass
class Fact:
    id: int
    ts: float
    text: str
    tags: list[str]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 1}


class Memory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.facts: list[Fact] = []
        if path.exists():
            for line in path.read_text("utf-8").splitlines():
                if line.strip():
                    self.facts.append(Fact(**json.loads(line)))

    def remember(self, text: str, tags: list[str] | None = None) -> Fact:
        text = text.strip()[:MAX_FACT_CHARS]
        if not text:
            raise ValueError("empty fact")
        with self._lock:
            fact = Fact(max((f.id for f in self.facts), default=0) + 1, time.time(), text,
                        [t.lower() for t in (tags or [])][:5])
            self.facts.append(fact)
            self.facts = self.facts[-MAX_FACTS:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(asdict(f), ensure_ascii=False) + "\n"
                                   for f in self.facts), "utf-8")
            tmp.replace(self.path)  # atomic: a crash never leaves a half-written file
        return fact

    def recall(self, query: str, limit: int = 8) -> list[Fact]:
        q = _words(query)
        if not q:
            return self.facts[-limit:]
        scored = []
        for f in self.facts:
            score = len(q & (_words(f.text) | set(f.tags)))
            if score:
                scored.append((score, f.ts, f))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [f for _, _, f in scored[:limit]]

    def forget(self, fact_id: int) -> bool:
        with self._lock:
            before = len(self.facts)
            self.facts = [f for f in self.facts if f.id != fact_id]
            if len(self.facts) == before:
                return False
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(asdict(f), ensure_ascii=False) + "\n"
                                   for f in self.facts), "utf-8")
            tmp.replace(self.path)
            return True
