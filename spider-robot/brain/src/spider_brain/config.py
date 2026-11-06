"""Brain settings from environment variables (prefix SB_) or a .env file."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Autonomy = Literal["autonomous", "guarded", "supervised"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class Settings(BaseSettings):
    # On servers put settings in /etc/spider-brain/brain.env and set SB_ENV_FILE to it.
    model_config = SettingsConfigDict(
        env_file=os.getenv("SB_ENV_FILE", ".env"), env_prefix="SB_", extra="ignore"
    )

    # Robot link ---------------------------------------------------------------
    robot_id: str = "spider-01"
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1884  # the simulator broker (infra/local/mosquitto-sim.conf)
    mqtt_tls: bool = False
    mqtt_client_id: str = "spider-brain"  # a unique suffix is added per process
    mqtt_ca_path: str | None = None
    mqtt_cert_path: str | None = None
    mqtt_key_path: str | None = None
    heartbeat_hz: float = 2.0
    online_timeout_s: float = 20.0

    # Planner ------------------------------------------------------------------
    planner: Literal["claude", "liquid"] = "claude"
    anthropic_api_key: str = Field(
        default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "SB_ANTHROPIC_API_KEY")
    )
    claude_model: str = "claude-opus-5-5"
    claude_effort: Effort = "medium"
    claude_fallbacks: bool = True  # server-side refusal fallback (Claude API only)
    claude_sees_images: bool = False  # also send camera frames to Claude (vision stays Liquid)
    max_task_usd: float = 1.0  # stop a task when its Claude spend passes this
    # list prices, USD per million tokens (claude-opus-5-5); update if you change model
    price_input_per_mtok: float = 4.0
    price_output_per_mtok: float = 20.0
    price_cache_read_per_mtok: float = 0.20
    price_cache_write_per_mtok: float = 5.0
    liquid_url: str = "http://127.0.0.1:8080/v1"  # llama-server with LFM2.5-1.2B-Instruct
    liquid_model: str = "LFM2.5-1.2B-Instruct"

    # Vision (Liquid LFM2.5-VL behind llama-server) -----------------------------
    vision_url: str = "http://127.0.0.1:8081/v1"
    vision_model: str = "LFM2.5-VL-1.6B"
    vision_timeout_s: float = 90.0

    # Behaviour ----------------------------------------------------------------
    autonomy: Autonomy = "guarded"
    max_steps: int = 25
    max_wall_seconds: int = 900
    walk_speed_slow: float = 0.03  # m/s
    walk_speed_normal: float = 0.06
    max_walk_m: float = 1.5  # per tool call
    approval_free_walk_m: float = 0.5  # longer walks are HIGH risk
    turn_speed_dps: float = 25.0
    gait: Literal["tripod", "ripple", "wave"] = "tripod"

    # Dashboard (same rules as desktop-agent: loopback only, token + origin) ----
    host: str = "127.0.0.1"
    port: int = 8765
    dashboard: bool = True
    dashboard_origins: list[str] = Field(default_factory=list)
    run_token_seconds: float = 5.0

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        if value not in LOOPBACK_HOSTS:
            raise ValueError(
                f"host {value!r} is not loopback. Reach the dashboard through an SSH/SSM tunnel "
                "or `tailscale serve`, never by binding to a public interface."
            )
        return value
