"""Provider-neutral types shared by the planner, the policy and the tool executor."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolOutcome:
    text: str
    is_error: bool = False
    image_jpeg: bytes | None = None


@dataclass
class PlanStep:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    thinking: str = ""
    stop_reason: str | None = None

    @property
    def done(self) -> bool:
        return not self.calls
