"""Run the command gateway. Settings come from SG_* environment variables."""

from __future__ import annotations

import asyncio
import logging
import os

from spider_common.link import MqttLink, MqttSettings

from .gateway import Gateway


def _settings() -> MqttSettings:
    env = os.environ.get
    return MqttSettings(
        host=env("SG_MQTT_HOST", "127.0.0.1"),
        port=int(env("SG_MQTT_PORT", "1884")),  # the simulator broker by default
        client_id="spider-gateway",
        tls=env("SG_MQTT_TLS", "0") == "1",
        ca_path=env("SG_MQTT_CA_PATH"),
        cert_path=env("SG_MQTT_CERT_PATH"),
        key_path=env("SG_MQTT_KEY_PATH"),
    )


async def _run() -> None:
    robot_id = os.environ.get("SG_ROBOT_ID", "spider-01")
    link = MqttLink(_settings(), Gateway.subscriptions(robot_id))
    gateway = Gateway(
        link, robot_id, source_timeout_s=float(os.environ.get("SG_SOURCE_TIMEOUT_S", "1.5"))
    )
    await link.start()
    try:
        await gateway.run()
    finally:
        await link.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
