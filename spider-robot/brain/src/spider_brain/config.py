"""Brain settings from environment variables (prefix SB_) or a .env file."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Autonomy = Literal["autonomous", "guarded", "supervised"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Gestures can only lead to these. Stop reduces motion; the rest speak or send a photo.
# Anything that moves the robot is refused here (the owner has not approved it).
SAFE_GESTURE_ACTIONS = frozenset({"stop", "greet", "describe", "photo"})
DEFAULT_GESTURE_ACTIONS = {
    "Open_Palm": "stop", "Thumb_Up": "greet", "Victory": "photo", "Pointing_Up": "describe",
}


class Settings(BaseSettings):
    # On servers put settings in /etc/spider-brain/brain.env and set SB_ENV_FILE to it.
    model_config = SettingsConfigDict(
        env_file=os.getenv("SB_ENV_FILE", ".env"), env_prefix="SB_", extra="ignore",
        populate_by_name=True,  # Settings(telegram_token=...) works as well as the env alias
    )

    # Robot link ---------------------------------------------------------------
    robot_id: str = "spider-01"
    # "remote" or "planner" = send through the command gateway on the Pi; None = straight to the
    # body. The local broker's ACL requires the gateway.
    robot_source: Literal["remote", "planner"] | None = None
    # With robot_source=planner, what the owner does by hand goes out at this higher priority.
    human_source: Literal["remote"] | None = None
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
    # "claude" = routed (simple/default tiers below); "liquid" = everything on the local model
    planner: Literal["claude", "liquid"] = "claude"
    anthropic_api_key: str = Field(
        default="", validation_alias=AliasChoices("ANTHROPIC_API_KEY", "SB_ANTHROPIC_API_KEY")
    )
    claude_model: str = "claude-opus-5-5"
    claude_effort: Effort = "medium"
    claude_fallbacks: bool = True  # server-side refusal fallback (Claude API only)
    claude_sees_images: bool = False  # also send camera frames to Claude (vision stays Liquid)
    max_task_usd: float = 1.0  # stop a task when its Claude spend passes this
    # list prices for models not in planner.PRICES, USD per million tokens
    price_input_per_mtok: float = 4.0
    price_output_per_mtok: float = 20.0
    price_cache_read_per_mtok: float = 0.20
    price_cache_write_per_mtok: float = 5.0
    liquid_url: str = "http://127.0.0.1:8080/v1"  # llama-server with LFM2.5-1.2B-Instruct
    liquid_model: str = "LFM2.5-1.2B-Instruct"

    # Model routing (the llm-gateway idea from the JobHunt repo) ----------------
    # A route is "anthropic:<model>", "liquid", or "compat:<model>" (any OpenAI-compatible
    # server: OpenAI, Kimi, a "free" provider; set compat_base_url + COMPAT_API_KEY).
    route_simple: str = "anthropic:claude-haiku-5-5"  # chat, questions, one-step commands
    route_default: str = "anthropic:claude-opus-5-5"  # multi-step robot tasks
    route_fallback: str = "liquid"  # used when the primary provider is down ("" = none)
    escalate_after_errors: int = 2  # simple tier -> default tier after N failed tool calls
    escalate_after_steps: int = 8  # ... or after N steps
    compat_base_url: str = ""
    compat_api_key: str = Field(
        default="", validation_alias=AliasChoices("COMPAT_API_KEY", "SB_COMPAT_API_KEY")
    )
    vision_fallback: str = "anthropic:claude-haiku-5-5"  # when the Liquid vision server fails

    # Skills and memory ----------------------------------------------------------
    # brain/skills first, then the repo's skills/ (all JobHunt skills, loadable on demand)
    skills_dirs: list[str] = Field(default_factory=lambda: ["skills", "../../skills"])
    always_on_skills: list[str] = Field(
        default_factory=lambda: ["robot-reasoning", "robot-conversation"]
    )
    memory_path: str = "data/memory.jsonl"

    # Voice (same stack as the repo's orchestrator.py: Gemini STT + Gemini TTS, gTTS fallback)
    gemini_api_key: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_API_KEY", "SB_GEMINI_API_KEY")
    )
    gemini_text_model: str = "gemini-2.5-flash"
    gemini_fallback_model: str = "gemini-2.5-flash"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    tts_voice: str = "Puck"
    voice_lang: str = "ar"  # gTTS fallback language when the text has no Arabic letters: "en"
    voice_replies: bool = True  # answer voice notes with a voice note

    # Telegram (owner-only bot: commands, approvals, alerts, voice notes) ---------
    telegram_token: str = Field(
        default="", validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "SB_TELEGRAM_TOKEN")
    )
    telegram_owner_ids: list[int] = Field(default_factory=list)  # your Telegram user id(s)

    # WhatsApp alerts through the repo's local voice-agent bridge (127.0.0.1:3050) -----
    whatsapp_bridge_url: str = ""  # e.g. http://127.0.0.1:3050 when the brain runs locally
    whatsapp_bridge_token: str = Field(
        default="", validation_alias=AliasChoices("BRIDGE_TOKEN", "SB_WHATSAPP_BRIDGE_TOKEN")
    )

    # Vision (Liquid LFM2.5-VL behind llama-server) -----------------------------
    vision_url: str = "http://127.0.0.1:8081/v1"
    vision_model: str = "LFM2.5-VL-1.6B"
    vision_timeout_s: float = 90.0

    # Perception: objects, faces, gestures (home server; uv sync --extra perception) ----------
    perception: bool = False
    perception_dir: str = "data/perception"  # models/, people/, faces.npz; brain/data is gitignored
    perception_detectors: list[str] = Field(default_factory=lambda: ["models/yolo26n.onnx"])
    perception_min_score: float = Field(0.35, gt=0, lt=1)
    perception_threads: int = Field(2, ge=1, le=6)  # the VLM and Whisper share this CPU
    face_threshold: float = 0.363  # SFace cosine at LFW; check with the calibration script
    face_margin: float = 0.05  # the best person must beat the second best by this much
    gesture_head: str = ""  # "models/gestures_mlp.npz" after a custom head is trained
    gesture_min_score: float = Field(0.6, gt=0, lt=1)
    watch_period_s: float = Field(0.6, ge=0.5)  # the gateway refuses snapshots < 0.5 s apart
    watch_minutes: float = Field(30.0, gt=0, le=240)
    gesture_actions: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_GESTURE_ACTIONS))
    gesture_anyone: list[str] = Field(default_factory=lambda: ["stop"])  # others: enrolled only

    # Workers for the Pi's voice loop (request and reply over MQTT) --------------
    ask_worker: bool = False
    # "liquid" or "compat:<model>"; NIM's kimi-k3.1-pro had no API on 2026-11-04, kimi-k3 does.
    ask_route: str = "liquid"
    ask_fallback: str = ""  # e.g. compat:moonshotai/kimi-k3 with SB_COMPAT_BASE_URL set
    ask_timeout_s: float = 30.0
    stt_worker: bool = False
    stt_model: str = "small"
    stt_device: str = "cpu"  # "cuda" after a GPU upgrade; nothing else changes
    stt_compute_type: str = "int8"
    stt_threads: int = 6
    stt_language: str = "ar"
    traces_path: str = "data/voice_traces.jsonl"

    # On-demand recording and mapping (off unless these are set) ---------------
    pi_ssh_target: str = ""  # e.g. spider@spider-pi (a Tailscale name)
    recordings_dir: str = "data/recordings"
    aws_worker_instance_id: str = ""
    aws_region: str = "ap-northeast-1"
    aws_worker_ssh_target: str = ""  # e.g. ubuntu@spider-worker (a Tailscale name)

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

    # Mobile app API: /v1 on the dashboard's port, published with `tailscale serve` -------------
    # Everything the app does goes out as the gateway's "remote" source, so the gateway's remote
    # caps and the body's limits apply. The app's own top speed lives in the gateway (SpeedLimit,
    # set from Settings) and is the one that counts; these two only cap it on the brain's side, at
    # most the body's gait limits.
    mobile: bool = False
    mobile_data_dir: str = "data/mobile"  # paired devices (token hashes) and the pairing code
    mobile_max_speed_mps: float = Field(0.12, gt=0.0, le=0.12)
    mobile_max_wz_rps: float = Field(0.6, gt=0.0, le=0.6)
    mobile_move_s: float = Field(1.0, gt=0.0, le=1.0)
    mobile_deadman_s: float = Field(0.6, gt=0.0, le=0.6)  # no drive renewal for this long: stop
    mobile_max_frame_age_s: float = Field(2.0, gt=0.0, le=2.0)  # no driving on an older frame
    mobile_pair_code_s: float = Field(120.0, gt=0.0, le=600.0)
    # Hold to talk from the app (/v1/talk): Whisper (the STT worker's model), then the first
    # of these routes that answers, in order. Comma-separated: "liquid", "compat:<model>",
    # "anthropic:<model>", "gemini:<model>", "lowi" (reserved: skipped until Lowi is
    # connected to the robot).
    talk_routes: str = "liquid"
    talk_max_s: float = Field(30.0, gt=0.0, le=60.0)  # longest clip the app may send
    talk_timeout_s: float = Field(45.0, gt=0.0, le=120.0)  # for every route together
    # Spoken answers come back as a WAV in Lowi's own Gemini voices (Arabic Fenrir, the owner's
    # pick; English Puck); without a Gemini key or network the phone uses its own voice.
    talk_speech: bool = True
    talk_voice_ar: str = "Fenrir"
    talk_voice_en: str = "Puck"

    @property
    def talk_route_list(self) -> list[str]:
        return [part.strip() for part in self.talk_routes.split(",") if part.strip()]

    @field_validator("talk_routes")
    @classmethod
    def _known_talk_routes(cls, value: str) -> str:
        for route in (part.strip() for part in value.split(",") if part.strip()):
            kind, _, model = route.partition(":")
            if kind not in ("liquid", "compat", "anthropic", "gemini", "lowi") or (
                    kind in ("compat", "anthropic", "gemini") and not model):
                raise ValueError(f"unknown talk route {route!r}: use liquid, compat:<model>, "
                                 "anthropic:<model>, gemini:<model> or lowi")
        return value

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_owner_ids)

    @property
    def approvals_available(self) -> bool:
        """Someone can press Approve: the dashboard or the owner's Telegram."""
        return self.dashboard or self.telegram_enabled

    @model_validator(mode="after")
    def _mobile_through_gateway(self) -> Settings:
        source = self.human_source or self.robot_source
        if self.mobile and source != "remote":
            raise ValueError(
                "SB_MOBILE needs the command gateway: set SB_ROBOT_SOURCE=planner and "
                "SB_HUMAN_SOURCE=remote, so the app is held to the remote caps."
            )
        return self

    @field_validator("gesture_actions")
    @classmethod
    def _gestures_never_move(cls, value: dict[str, str]) -> dict[str, str]:
        for gesture, action in value.items():
            if action in SAFE_GESTURE_ACTIONS or (action.startswith("say:") and len(action) > 4):
                continue
            raise ValueError(f"gesture {gesture!r}: action {action!r} is not allowed; gestures "
                             f"may only {sorted(SAFE_GESTURE_ACTIONS)} or say:<text>")
        return value

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        if value not in LOOPBACK_HOSTS:
            raise ValueError(
                f"host {value!r} is not loopback. Reach the dashboard through an SSH/SSM tunnel "
                "or `tailscale serve`, never by binding to a public interface."
            )
        return value
