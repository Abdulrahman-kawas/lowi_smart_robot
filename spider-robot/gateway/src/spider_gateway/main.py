"""Run the command gateway. Settings come from SG_* environment variables."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from spider_common.link import MqttLink, MqttSettings
from spider_common.obs import setup_logging
from spider_common.protocol import GatewayStatus, Topics

from .gateway import Gateway, GatewayConfig
from .policy import load_policies


def _settings() -> MqttSettings:
    env = os.environ.get
    secret = env("SG_MQTT_PASSWORD_FILE")
    return MqttSettings(
        host=env("SG_MQTT_HOST", "127.0.0.1"),
        port=int(env("SG_MQTT_PORT", "1884")),  # the simulator broker by default
        client_id="spider-gateway",
        tls=env("SG_MQTT_TLS", "0") == "1",
        ca_path=env("SG_MQTT_CA_PATH"),
        cert_path=env("SG_MQTT_CERT_PATH"),
        key_path=env("SG_MQTT_KEY_PATH"),
        username=env("SG_MQTT_USERNAME"),
        password=Path(secret).read_text("utf-8").strip() if secret else None,
        reconnect_max_s=2,  # the broker is on this machine
    )


async def _run() -> None:
    robot_id = os.environ.get("SG_ROBOT_ID", "spider-01")
    will = GatewayStatus(robot_id=robot_id, online=False)
    link = MqttLink(
        _settings(),
        Gateway.subscriptions(robot_id),
        will=(Topics(robot_id).gateway_status, will.model_dump_json().encode()),
        will_retain=True,
    )
    config = GatewayConfig(
        source_timeout_s=float(os.environ.get("SG_SOURCE_TIMEOUT_S", "1.5")),
        stop_holdoff_s=float(os.environ.get("SG_STOP_HOLDOFF_S", "2.0")),
        bench_enabled=os.environ.get("SG_BENCH", "0") == "1",
        state_dir=Path(os.environ.get("SG_STATE_DIR", "/var/lib/spider-gateway")),
    )
    policies = load_policies(os.environ.get("SG_POLICY_FILE"))
    gateway = Gateway(link, robot_id, config=config, policies=policies)
    await link.start()
    try:
        await gateway.run()
    finally:
        await link.stop()


def main() -> None:
    setup_logging(os.environ.get("SG_LOG_LEVEL", "INFO"), service="spider-gateway")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
