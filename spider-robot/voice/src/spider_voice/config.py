"""Voice configuration. Every engine is chosen here, so swapping one needs no code change."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .stopwords import DEFAULT_ESTOP_PHRASES, DEFAULT_STOP_WORDS


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MqttCfg(_M):
    host: str = "127.0.0.1"
    port: int = 1884
    tls: bool = False
    username: str | None = None  # loopback listener on the Pi: no certificate, no clock needed
    password_file: str | None = None
    reconnect_max_s: int = 2
    client_id: str = "spider-voice"


class AudioCfg(_M):
    sample_rate: int = 16000
    frame_ms: Literal[10, 20, 30] = 20
    capture_device: str = "default"
    playback_device: str = "default"
    vad_aggressiveness: int = Field(2, ge=0, le=3)
    min_rms_dbfs: float = -45.0  # frames quieter than this are never speech
    end_of_speech_ms: int = 300
    max_utterance_s: float = 8.0
    short_utterance_s: float = 1.6  # always gets an STT slot at once; stop words are this short


class WhisperLocalCfg(_M):
    model: str = "tiny"
    compute_type: str = "int8"
    cpu_threads: int = 3
    workers: int = 2  # a short utterance is never queued behind a long one
    language: str = "ar"
    timeout_s: float = 20.0  # the estimate is 3-8 s, more with overlaps; bench V1 sets it
    # Biases a small model toward the command words. Bench-check that silence does not echo it.
    prompt: str = "قف، وقف، امشي قدام، ارجع ورا، لف يمين، لف يسار، شوف"


class SttCfg(_M):
    primary: Literal["whisper_local", "whisper_server"] = "whisper_local"
    escalate: Literal["whisper_server", "none"] = "none"
    whisper_local: WhisperLocalCfg = Field(default_factory=WhisperLocalCfg)
    server_timeout_s: float = 4.0
    server_retry_after_s: float = 30.0  # after a timeout, skip the server for this long
    max_no_speech_prob: float = 0.7
    min_avg_logprob: float = -1.2
    escalate_below_logprob: float = -0.8


class PiperCfg(_M):
    model_path: str = "/opt/spider/models/ar_JO-kareem-low.onnx"


class EspeakCfg(_M):
    voice: str = "ar"
    sample_rate: int = 22050


class TtsCfg(_M):
    primary: Literal["piper", "espeak"] = "piper"
    fallback: Literal["espeak", "none"] = "espeak"
    piper: PiperCfg = Field(default_factory=PiperCfg)
    espeak: EspeakCfg = Field(default_factory=EspeakCfg)


class RouterCfg(_M):
    kind: Literal["ollama"] = "ollama"
    url: str = "http://127.0.0.1:11434"
    model: str = "hf.co/LiquidAI/LFM2.5-350M-GGUF:Q4_K_M"
    timeout_s: float = 10.0  # a whole reply, on a Pi 4 that may manage only a few tokens a second


class EscalationCfg(_M):
    """Vision and hard questions go to the brain over MQTT. Their answers are only ever spoken."""

    enabled: bool = True
    timeout_s: float = 45.0
    filler: str = "لحظة أشوف"
    failure: str = "ما قدرت أجاوب هلأ"


class MotionCfg(_M):
    speed_mps: float = 0.06
    turn_rps: float = 0.4
    duration_s: float = 1.5
    gait: Literal["tripod", "ripple", "wave"] = "tripod"
    say_max_chars: int = 30  # while moving, speech stays short so the deaf window stays short
    move_speed: float = Field(0.5, gt=0.0, le=1.0)  # expressive moves (dance, wave, ...)


class VoiceConfig(_M):
    robot_id: str = "spider-01"
    mqtt: MqttCfg = Field(default_factory=MqttCfg)
    audio: AudioCfg = Field(default_factory=AudioCfg)
    stt: SttCfg = Field(default_factory=SttCfg)
    tts: TtsCfg = Field(default_factory=TtsCfg)
    router: RouterCfg = Field(default_factory=RouterCfg)
    escalation: EscalationCfg = Field(default_factory=EscalationCfg)
    motion: MotionCfg = Field(default_factory=MotionCfg)
    wake_words: tuple[str, ...] = ("لوي", "لاوي", "سبايدر", "عنكبوت", "spider")
    wake_required: bool = True
    attention_window_s: float = 8.0
    stop_words: tuple[str, ...] = DEFAULT_STOP_WORDS
    emergency_words: tuple[str, ...] = DEFAULT_ESTOP_PHRASES
    # Stop on any speech onset while walking. Off until the bench shows gait noise does not trip it.
    stop_on_speech_onset: bool = False
    speech_onset_cooldown_s: float = 1.0
    # A motion from speech older than this is discarded. Bench V1 sets the final value.
    max_motion_age_s: float = 6.0
    max_short_queue: int = 8  # short utterances waiting for an STT slot; the oldest goes first
    heartbeat_hz: float = 2.0
    grammar_max_words: int = 6


def load_config(path: str | Path) -> VoiceConfig:
    return VoiceConfig.model_validate(yaml.safe_load(Path(path).read_text("utf-8")) or {})
