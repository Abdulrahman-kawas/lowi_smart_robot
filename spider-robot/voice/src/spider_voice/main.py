"""spider-voice entry point: microphone, pipeline, gateway connection, health."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from spider_common.link import MqttLink, MqttSettings
from spider_common.obs import setup_logging
from spider_common.protocol import HealthReport, Topics, VoiceTurn

from . import registry
from .adapters.vad_webrtc import WebRtcVad
from .audio import AplayOutput, ArecordCapture, frame_rms, is_speech_frame
from .config import VoiceConfig, load_config
from .gwclient import GatewayClient
from .pipeline import VoicePipeline

log = logging.getLogger("spider_voice")
HEALTH_PERIOD_S = 5.0
STT_TIMEOUTS_DEGRADED = 3


def build_link(cfg: VoiceConfig) -> MqttLink:
    t = Topics(cfg.robot_id)
    will = HealthReport(robot_id=cfg.robot_id, service="voice", level="down", detail="lost")
    m = cfg.mqtt
    password = Path(m.password_file).read_text("utf-8").strip() if m.password_file else None
    return MqttLink(
        MqttSettings(host=m.host, port=m.port, client_id=m.client_id, tls=m.tls,
                     username=m.username, password=password, reconnect_max_s=m.reconnect_max_s),
        subscriptions=GatewayClient.subscriptions(cfg.robot_id),
        will=(t.health("voice"), will.model_dump_json().encode()),
        will_retain=True,
    )


def health_report(cfg: VoiceConfig, pipeline: VoicePipeline, connected: bool) -> HealthReport:
    level = "ok" if connected and pipeline.ready else "degraded"
    detail = "" if pipeline.ready else "starting"
    if pipeline.stt_timeouts >= STT_TIMEOUTS_DEGRADED:
        level, detail = "degraded", "speech recognition keeps timing out"
    metrics = {f"stt_{k}": v for k, v in pipeline.stt_hist.snapshot().items()}
    metrics |= {f"route_{k}": v for k, v in pipeline.route_hist.snapshot().items()}
    metrics |= {"turns": float(pipeline.turns), "failures": float(pipeline.failures),
                "dropped": float(pipeline.dropped),
                "stt_timeouts": float(pipeline.stt_timeouts)}
    return HealthReport(robot_id=cfg.robot_id, service="voice", level=level, detail=detail,
                        metrics=metrics)


async def _capture(cfg: VoiceConfig, pipeline: VoicePipeline, vad: WebRtcVad) -> None:
    a = cfg.audio
    await pipeline.prepare()  # models in memory and phrases rendered before anyone is listened to
    log.info("spider-voice ready")
    capture = ArecordCapture(a.capture_device, a.sample_rate, a.frame_ms)
    async for frame in capture.frames():
        rms = frame_rms(frame)
        pipeline.on_frame(frame, is_speech_frame(vad.is_speech(frame), rms, a.min_rms_dbfs), rms)


async def _health(link: MqttLink, cfg: VoiceConfig, pipeline: VoicePipeline) -> None:
    topic = Topics(cfg.robot_id).health("voice")
    while True:
        report = health_report(cfg, pipeline, link.connected.is_set())
        link.publish(topic, report.model_dump_json(), qos=1, retain=True)
        await asyncio.sleep(HEALTH_PERIOD_S)


async def run(cfg: VoiceConfig) -> None:
    link = build_link(cfg)
    gateway = GatewayClient(link, cfg.robot_id)
    topics = Topics(cfg.robot_id)

    def publish_turn(turn: VoiceTurn) -> None:
        link.publish(topics.voice_turn, turn.model_dump_json())

    pipeline = VoicePipeline(
        cfg,
        stt=registry.build_stt(cfg, gateway.rpc),
        tts=registry.build_tts(cfg),
        router=registry.build_router(cfg),
        gateway=gateway,
        audio=AplayOutput(cfg.audio.playback_device),
        tts_fallback=registry.build_tts_fallback(cfg),
        stt_escalate=registry.build_stt_escalation(cfg, gateway.rpc),
        vision=registry.build_vision(cfg, gateway.rpc),
        answerers=registry.build_answerers(cfg, gateway.rpc),
        publish_turn=publish_turn,
    )
    vad = WebRtcVad(cfg.audio.vad_aggressiveness, cfg.audio.sample_rate)
    await link.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = [
        asyncio.create_task(gateway.run(), name="link"),
        asyncio.create_task(gateway.heartbeat_loop(cfg.heartbeat_hz), name="heartbeat"),
        asyncio.create_task(_capture(cfg, pipeline, vad), name="capture"),
        asyncio.create_task(_health(link, cfg, pipeline), name="health"),
    ]
    log.info("spider-voice running")
    waiter = asyncio.create_task(stop.wait())
    done, _ = await asyncio.wait([waiter, *tasks], return_when=asyncio.FIRST_COMPLETED)
    for task in done:
        if task is not waiter and task.exception():
            log.error("task %s crashed: %r", task.get_name(), task.exception())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await link.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-voice")
    parser.add_argument("--config", default="/etc/spider/voice.yaml")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    setup_logging(args.log_level, service="spider-voice")
    asyncio.run(run(load_config(args.config)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
