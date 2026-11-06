"""Agent Skills for the robot brain, in the same open format as the repo's `skills/` folder.

Each skill is a folder with a `SKILL.md` (YAML frontmatter: name, description) and optional
`references/*.md`. Like the JobHunt assistant:
  * "always on" skills are put in full into the cached system prompt,
  * every other skill is listed by name + description, and the planner loads one with the
    `load_skill(name, reference)` tool when it needs it.

Directories are searched in order; the first skill with a given name wins. By default the
brain's own `brain/skills/` comes first, then the repo's `skills/` (all 18 JobHunt skills:
CV writing, Japanese business writing, interview coaching, career coaching, ...).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_NAME_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    references: dict[str, Path] = field(default_factory=dict)


def parse_skill(skill_dir: Path) -> Skill | None:
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return None
    text = md.read_text("utf-8")
    m = _FRONT.match(text)
    if not m:
        return None
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"')
    name = meta.get("name", "")
    if not _NAME_OK.match(name):
        return None
    refs = {}
    ref_dir = skill_dir / "references"
    if ref_dir.is_dir():
        refs = {p.stem: p for p in sorted(ref_dir.glob("*.md"))}
    return Skill(name, meta.get("description", ""), text[m.end():].strip(), refs)


class SkillLibrary:
    def __init__(self, dirs: list[Path], always_on: list[str], max_chars: int = 40_000) -> None:
        self.skills: dict[str, Skill] = {}
        for d in dirs:
            if not d.is_dir():
                continue
            for sub in sorted(p for p in d.iterdir() if p.is_dir()):
                skill = parse_skill(sub)
                if skill is not None and skill.name not in self.skills:
                    self.skills[skill.name] = skill
        self.always_on = [n for n in always_on if n in self.skills]
        self.max_chars = max_chars

    def system_text(self) -> str:
        """Static text for the system prompt: always-on bodies + an index of the rest."""
        parts = [f"<skill name=\"{n}\">\n{self.skills[n].body}\n</skill>" for n in self.always_on]
        others = [s for n, s in sorted(self.skills.items()) if n not in self.always_on]
        if others:
            lines = "\n".join(f"- {s.name}: {s.description}" for s in others)
            parts.append(
                "Other skills you can load with the load_skill tool when a task needs them "
                "(knowledge tasks such as CVs, Japanese business writing or interview "
                "practice need no robot tools):\n" + lines
            )
        return "\n\n".join(parts)

    def load(self, name: str, reference: str = "") -> str:
        skill = self.skills.get(name)
        if skill is None:
            raise KeyError(f"unknown skill {name!r}; available: {', '.join(sorted(self.skills))}")
        if not reference:
            refs = ", ".join(skill.references) or "none"
            return f"{skill.body}\n\n(references you can load: {refs})"[: self.max_chars]
        path = skill.references.get(reference)  # only listed files: no path traversal
        if path is None:
            raise KeyError(f"skill {name!r} has no reference {reference!r}")
        return path.read_text("utf-8")[: self.max_chars]
