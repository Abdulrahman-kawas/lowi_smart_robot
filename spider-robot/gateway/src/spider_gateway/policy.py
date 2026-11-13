"""Per-source limits the gateway enforces before anything reaches the body.

These add to the body's own limits and replace none of them. A remote operator is not next to the
robot, so remote motion is slower and shorter than local voice: if the network dies mid-command the
robot has moved at most max_speed_mps * max_duration_s before its Move expires.
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


# The bench source exists only while SG_BENCH=1, for a person at the robot during M3 and M4.
BENCH_POLICY = SourcePolicy(max_speed_mps=0.12, max_wz_rps=0.6, max_duration_s=3.0,
                            max_excess_delay_s=0.5, allow_moves=True)

DEFAULT_POLICIES: dict[str, SourcePolicy] = {
    "voice": SourcePolicy(max_speed_mps=0.08, max_wz_rps=0.5, max_duration_s=2.0,
                          max_excess_delay_s=0.5, allow_moves=True),
    "remote": SourcePolicy(max_speed_mps=0.05, max_wz_rps=0.3, max_duration_s=1.0,
                           max_excess_delay_s=0.75, may_release_estop=True,
                           needs_frame_proof=True),
    "planner": SourcePolicy(max_speed_mps=0.06, max_wz_rps=0.45, max_duration_s=1.0,
                            max_excess_delay_s=0.75),
}


def check_order(policies: dict[str, SourcePolicy]) -> None:
    """Refuse a configuration that would let a remote operator outrun local voice."""
    voice, remote = policies["voice"], policies["remote"]
    if remote.max_speed_mps > voice.max_speed_mps or remote.max_wz_rps > voice.max_wz_rps:
        raise ValueError("remote caps must not exceed voice caps")
    if remote.max_duration_s > voice.max_duration_s:
        raise ValueError("remote max_duration_s must not exceed voice max_duration_s")
    if remote.may_release_estop and not remote.needs_frame_proof:
        raise ValueError("a remote E-stop release must require a fresh frame and confirmation")
    if policies["planner"].may_release_estop or voice.may_release_estop:
        raise ValueError("only the remote source may release an E-stop")
    if policies["planner"].allow_moves:
        raise ValueError("the planner may never start expressive moves")


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
