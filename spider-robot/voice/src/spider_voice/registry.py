"""Builds the engines named in the config. The only place that chooses an adapter."""

from __future__ import annotations

from .adapters.ask_rpc import RpcAsk
from .adapters.router_ollama import OllamaRouter
from .adapters.stt_chain import ServerFirstSTT
from .adapters.stt_rpc import RpcStt
from .adapters.stt_whisper import WhisperLocalSTT
from .adapters.tts_espeak import EspeakTTS
from .adapters.tts_piper import PiperTTS
from .config import VoiceConfig
from .interfaces import STT, TTS, Answerer, Router, Vision
from .rpc import RpcClient


def _server_stt(cfg: VoiceConfig, rpc: RpcClient) -> STT:
    return RpcStt(rpc, cfg.stt.server_timeout_s, cfg.stt.server_retry_after_s,
                  cfg.stt.whisper_local.prompt)


def build_stt(cfg: VoiceConfig, rpc: RpcClient | None = None) -> STT:
    """Without rpc (the bench tool, which never connects) this is always the local model."""
    local = WhisperLocalSTT(cfg.stt.whisper_local)
    if cfg.stt.primary == "whisper_server" and rpc is not None:
        return ServerFirstSTT(_server_stt(cfg, rpc), local)
    return local


def build_stt_escalation(cfg: VoiceConfig, rpc: RpcClient) -> STT | None:
    if cfg.stt.escalate != "whisper_server" or cfg.stt.primary == "whisper_server":
        return None  # with the server already first, asking it again would add nothing
    return _server_stt(cfg, rpc)


def build_tts(cfg: VoiceConfig) -> TTS:
    return EspeakTTS(cfg.tts.espeak) if cfg.tts.primary == "espeak" else PiperTTS(cfg.tts.piper)


def build_tts_fallback(cfg: VoiceConfig) -> TTS | None:
    return EspeakTTS(cfg.tts.espeak) if cfg.tts.fallback == "espeak" else None


def build_router(cfg: VoiceConfig) -> Router:
    return OllamaRouter(cfg.router)


def build_vision(cfg: VoiceConfig, rpc: RpcClient) -> list[Vision]:
    return [RpcAsk(rpc, cfg.escalation.timeout_s, True)] if cfg.escalation.enabled else []


def build_answerers(cfg: VoiceConfig, rpc: RpcClient) -> list[Answerer]:
    return [RpcAsk(rpc, cfg.escalation.timeout_s, False)] if cfg.escalation.enabled else []
