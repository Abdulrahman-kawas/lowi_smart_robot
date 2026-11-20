"""Per-source limits the gateway enforces before anything reaches the body.

These add to the body's own limits and replace none of them. A remote operator is not next to the
robot, so remote moves are shorter than local voice: if the network dies mid-command the robot has
moved at most speed * max_duration_s before its Move expires (12 cm at the remote ceiling).

The remote source's speed and turn rate are the app's own setting (SpeedLimit, kept by the gateway);
remote max_speed_mps and max_wz_rps here are only its ceiling.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_speed_mps: float = Field(gt=0.0, le=0.5)
    max_wz_rps: float = Field(gt=0.0, le=2.0)
    max_duration_s: float = Field(gt=0.0, le=10.0)
    max_excess_delay_s: float = Field(gt=0.0, le=5.0)  # later than its best recent delay: refused
    may_release_estop: bool = False
    needs_frame_proof: bool = False  # release must name a fresh camera frame and be confirmed
    min_snapshot_period_s: float = Field(0.5, ge=0.0)
    allow_moves: bool = False  # Perform and Reach (expressive moves); never for the planner
    max_move_speed: float = Field(1.0, gt=0.0, le=1.0)  # the app's own setting decides below this
    local_only_moves: list[str] = Field(default_factory=list)  # closed to the app unless empty
    allow_look: bool = True  # Look (camera pan). Never for the planner: see check_order
    min_look_period_s: float = Field(0.2, ge=0.0)  # at most 5 Looks a second per source


# The bench source exists only while SG_BENCH=1, for a person at the robot during M3 and M4.
BENCH_POLICY = SourcePolicy(max_speed_mps=0.12, max_wz_rps=0.6, max_duration_s=3.0,
                            max_excess_delay_s=0.5, allow_moves=True)

DEFAULT_POLICIES: dict[str, SourcePolicy] = {
    "voice": SourcePolicy(max_speed_mps=0.08, max_wz_rps=0.5, max_duration_s=2.0,
                          max_excess_delay_s=0.5, allow_moves=True),
    # Speed and turn rate: the ceiling of the app's own setting, at the body's gait limits.
    "remote": SourcePolicy(max_speed_mps=0.12, max_wz_rps=0.6, max_duration_s=1.0,
                           max_excess_delay_s=0.75, allow_moves=True,
                           may_release_estop=True, needs_frame_proof=True),
    "planner": SourcePolicy(max_speed_mps=0.06, max_wz_rps=0.45, max_duration_s=1.0,
                            max_excess_delay_s=0.75, allow_look=False),
}


def check_order(policies: dict[str, SourcePolicy]) -> None:
    """Refuse a policy file that breaks the rules between the sources.

    Remote speed and turn rate may be above voice: the owner decided on 2026-11-20 that the app
    sets the robot's speed, and its own top speed up to the body's limits (0.12 m/s, 0.6 rad/s).
    The remote ceiling here bounds that setting; the body's own checks are unchanged. A remote
    Move still may not last longer than a voice one, and every E-stop rule stays.
    """
    voice, remote = policies["voice"], policies["remote"]
    if remote.max_duration_s > voice.max_duration_s:
        raise ValueError("remote max_duration_s must not exceed voice max_duration_s")
    if remote.may_release_estop and not remote.needs_frame_proof:
        raise ValueError("a remote E-stop release must require a fresh frame and confirmation")
    if policies["planner"].may_release_estop or voice.may_release_estop:
        raise ValueError("only the remote source may release an E-stop")
    if policies["planner"].allow_moves:
        raise ValueError("the planner may never start expressive moves")
    if policies["planner"].allow_look:
        raise ValueError("the planner may not turn the camera")


def load_policies(path: str | Path | None = None) -> dict[str, SourcePolicy]:
    """Defaults, with field-level overrides per source from a YAML file."""
    merged = {name: policy.model_dump() for name, policy in DEFAULT_POLICIES.items()}
    if path is not None:
        data = yaml.safe_load(Path(path).read_text("utf-8")) or {}
        unknown = set(data) - set(merged)
        if unknown:
            raise ValueError(f"unknown sources in {path}: {sorted(unknown)}")
        for name, override in data.items():
            merged[name].update(override)
    policies = {name: SourcePolicy.model_validate(values) for name, values in merged.items()}
    check_order(policies)
    return policies
