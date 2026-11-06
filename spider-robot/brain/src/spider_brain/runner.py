"""Entry points: MQTT link factory and the one-shot `run_task` (used by `spider-brain run`).

Since Part 2 the real work lives in service.BrainService; run_task starts a service for one
task (no Telegram, no WhatsApp), runs it, and shuts it down.
"""

from __future__ import annotations

import os

from spider_common.link import Link, MqttLink, MqttSettings

from .config import Settings
from .planner import Planner
from .robot_client import RobotClient


def build_link(settings: Settings, role: str = "run") -> MqttLink:
    # A unique client id per process: AWS IoT disconnects the older of two identical ids,
    # so `serve` and `teleop` would otherwise keep kicking each other off. The IoT policy and
    # the Mosquitto ACL allow the "spider-brain" prefix.
    client_id = f"{settings.mqtt_client_id}-{role}-{os.getpid()}"
    return MqttLink(
        MqttSettings(
            host=settings.mqtt_host, port=settings.mqtt_port, client_id=client_id,
            tls=settings.mqtt_tls, ca_path=settings.mqtt_ca_path,
            cert_path=settings.mqtt_cert_path, key_path=settings.mqtt_key_path,
        ),
        subscriptions=RobotClient.subscriptions(settings.robot_id),
    )


async def run_task(
    task: str,
    settings: Settings,
    *,
    link: Link | None = None,
    planner: Planner | None = None,
    vision=None,
    tier: str = "default",
) -> str:
    from .service import BrainService

    one_shot = settings.model_copy(update={"telegram_token": "", "whatsapp_bridge_url": ""})
    svc = BrainService(one_shot, link=link, vision=vision, role="run")
    await svc.start()
    try:
        return await svc.run_task(task, tier=tier, planner=planner, require_robot=True)
    finally:
        await svc.stop()
