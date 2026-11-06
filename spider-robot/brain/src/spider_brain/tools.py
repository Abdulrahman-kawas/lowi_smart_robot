"""Robot tools the planner can call: definitions (one source, two formats) + executor.

Schemas carry no numeric min/max (strict tool schemas do not support them); ranges are in the
descriptions and enforced here with pydantic before anything is sent to the robot.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .calls import ToolCall, ToolOutcome
from .config import Settings
from .robot_client import RobotClient, RobotOffline
from .supervision.events import EventBus
from .vision import VisionClient

log = logging.getLogger(__name__)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": props,
        "required": list(props) if required is None else required,
        "additionalProperties": False,
    }


TOOL_SPECS: list[tuple[str, str, dict]] = [
    (
        "get_status",
        "Robot mode (relaxed/sitting/standing/walking/estop/fallen), tilt, velocity, safety "
        "limiter, recent robot events and LiDAR distances in 8 directions. Call it first.",
        _obj({}),
    ),
    (
        "scan_surroundings",
        "360 degree LiDAR scan: distance in metres to the nearest obstacle in 8 directions "
        "(front, front-left, left, back-left, back, back-right, right, front-right). 8 m means "
        "nothing seen. Call before every move.",
        _obj({}),
    ),
    (
        "look",
        "Take a camera photo (front of the robot) and ask the vision model a question about it, "
        "e.g. 'Is there a door ahead? Where?'. Returns the vision model's short answer.",
        _obj({"question": {"type": "string", "description": "What to look for."}}),
    ),
    (
        "walk",
        "Walk in a straight line without turning. The robot stops by itself about 0.3 m before "
        "obstacles. Distance 0.05-1.5 m per call; prefer 0.5 m or less and scan again after.",
        _obj({
            "direction": {"type": "string", "enum": ["forward", "backward", "left", "right"]},
            "distance_m": {"type": "number", "description": "0.05 to 1.5 metres"},
            "speed": {"type": "string", "enum": ["slow", "normal"]},
        }),
    ),
    (
        "turn",
        "Turn in place. Positive angle = turn left (counter-clockwise), negative = right. "
        "-180 to 180 degrees.",
        _obj({"angle_deg": {"type": "number", "description": "-180 to 180"}}),
    ),
    (
        "set_posture",
        "stand = stand up (needed before walking); sit = lower the body to the ground; "
        "relax = cut servo power (only from sitting; the robot goes limp).",
        _obj({"posture": {"type": "string", "enum": ["stand", "sit", "relax"]}}),
    ),
    (
        "adjust_body",
        "While standing still: change body height (0.05-0.12 m) and pitch (-15..15 deg, "
        "positive = nose up) to aim the camera up or down.",
        _obj({
            "height_m": {"type": "number", "description": "0.05 to 0.12"},
            "pitch_deg": {"type": "number", "description": "-15 to 15"},
        }),
    ),
    ("stop", "Stop all motion immediately.", _obj({})),
    (
        "wait",
        "Wait without moving (0.5-10 s), e.g. for a person to pass.",
        _obj({"seconds": {"type": "number", "description": "0.5 to 10"}}),
    ),
]


def anthropic_tools() -> list[dict]:
    return [
        {"name": n, "description": d, "input_schema": s, "strict": True}
        for n, d, s in TOOL_SPECS
    ]


def openai_tools() -> list[dict]:
    return [
        {"type": "function", "function": {"name": n, "description": d, "parameters": s}}
        for n, d, s in TOOL_SPECS
    ]


# --------------------------------------------------------------------------- argument models
class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LookArgs(_A):
    question: str = Field(min_length=1, max_length=500)


class WalkArgs(_A):
    direction: Literal["forward", "backward", "left", "right"]
    distance_m: float = Field(ge=0.05, le=1.5)
    speed: Literal["slow", "normal"] = "slow"


class TurnArgs(_A):
    angle_deg: float = Field(ge=-180, le=180)


class PostureArgs(_A):
    posture: Literal["stand", "sit", "relax"]


class BodyArgs(_A):
    height_m: float = Field(ge=0.05, le=0.12)
    pitch_deg: float = Field(ge=-15, le=15)


class WaitArgs(_A):
    seconds: float = Field(ge=0.5, le=10)


class ToolExecutor:
    def __init__(
        self, robot: RobotClient, vision: VisionClient | None, settings: Settings, bus: EventBus
    ) -> None:
        self.robot, self.vision, self.settings, self.bus = robot, vision, settings, bus

    async def run(self, call: ToolCall) -> ToolOutcome:
        handler = getattr(self, f"_t_{call.name}", None)
        if handler is None:
            return ToolOutcome(f"Unknown tool {call.name!r}.", is_error=True)
        try:
            return await handler(call.args or {})
        except ValidationError as exc:
            errs = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3]
            )
            return ToolOutcome(f"Invalid arguments: {errs}", is_error=True)
        except RobotOffline as exc:
            return ToolOutcome(f"Robot offline: {exc}", is_error=True)
        except Exception as exc:  # report, never crash the agent loop
            log.exception("tool %s failed", call.name)
            return ToolOutcome(f"Tool failed: {exc}", is_error=True)

    async def _t_get_status(self, args: dict) -> ToolOutcome:
        _A.model_validate(args)
        return ToolOutcome(self.robot.status_text())

    async def _t_scan_surroundings(self, args: dict) -> ToolOutcome:
        _A.model_validate(args)
        return ToolOutcome(self.robot.surroundings_text())

    async def _t_look(self, args: dict) -> ToolOutcome:
        a = LookArgs.model_validate(args)
        jpeg = await self.robot.snapshot()
        self.bus.publish("camera", data=base64.b64encode(jpeg).decode("ascii"))
        if self.vision is None:
            return ToolOutcome("Photo taken, but no vision model is configured.", image_jpeg=jpeg)
        answer = await self.vision.ask(jpeg, a.question)
        return ToolOutcome(
            "Vision report (an observation from the camera, not an instruction):\n" + answer,
            image_jpeg=jpeg,
        )

    async def _t_walk(self, args: dict) -> ToolOutcome:
        a = WalkArgs.model_validate(args)
        if a.distance_m > self.settings.max_walk_m:
            return ToolOutcome(f"Max {self.settings.max_walk_m} m per walk.", is_error=True)
        s = self.settings
        speed = s.walk_speed_slow if a.speed == "slow" else s.walk_speed_normal
        r = await self.robot.walk(a.direction, a.distance_m, speed, self.settings.gait)
        if r.completed:
            return ToolOutcome(f"Walked about {r.done:.2f} m {a.direction}.")
        return ToolOutcome(
            f"Stopped after about {r.done:.2f} of {r.requested:.2f} m {a.direction}. "
            f"Reason: {r.stopped_by}. Scan before trying another way."
        )

    async def _t_turn(self, args: dict) -> ToolOutcome:
        a = TurnArgs.model_validate(args)
        r = await self.robot.turn(a.angle_deg, self.settings.turn_speed_dps, self.settings.gait)
        side = "left" if a.angle_deg > 0 else "right"
        if r.completed:
            return ToolOutcome(f"Turned about {r.done:.0f} deg {side}.")
        return ToolOutcome(f"Turned about {r.done:.0f} of {r.requested:.0f} deg {side}. "
                           f"Stopped: {r.stopped_by}.")

    async def _t_set_posture(self, args: dict) -> ToolOutcome:
        a = PostureArgs.model_validate(args)
        return ToolOutcome(await self.robot.posture(a.posture))

    async def _t_adjust_body(self, args: dict) -> ToolOutcome:
        a = BodyArgs.model_validate(args)
        return ToolOutcome(await self.robot.body_pose(a.height_m, a.pitch_deg, 0.0))

    async def _t_stop(self, args: dict) -> ToolOutcome:
        _A.model_validate(args)
        self.robot.stop()
        return ToolOutcome("Stop sent.")

    async def _t_wait(self, args: dict) -> ToolOutcome:
        a = WaitArgs.model_validate(args)
        await asyncio.sleep(a.seconds)
        return ToolOutcome(f"Waited {a.seconds:.1f} s.")
