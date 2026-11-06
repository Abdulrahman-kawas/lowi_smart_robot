"""Wire everything together: link + robot client + planner + vision + dashboard + graph."""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import uuid

from spider_common.link import Link, MqttLink, MqttSettings

from .config import Settings
from .graph import build_graph
from .planner import Planner, make_planner
from .robot_client import RobotClient
from .supervision.events import EventBus
from .supervision.server import create_app
from .supervision.supervisor import Stopped, Supervisor
from .tools import ToolExecutor
from .vision import VisionClient


def build_link(settings: Settings, role: str = "run") -> MqttLink:
    # A unique client id per process: AWS IoT disconnects the older of two identical ids,
    # so `run` and `teleop` would otherwise keep kicking each other off. The IoT policy and
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
    vision: VisionClient | None = None,
) -> str:
    bus = EventBus()
    supervisor = Supervisor(bus)
    link = link or build_link(settings)
    robot = RobotClient(link, settings.robot_id, bus)
    vision = vision or VisionClient(settings.vision_url, settings.vision_model,
                                    settings.vision_timeout_s)
    planner = planner or make_planner(settings)
    executor = ToolExecutor(robot, vision, settings, bus)
    graph = build_graph(settings, planner, executor, supervisor)

    await link.start()
    background = [
        asyncio.create_task(robot.run(), name="robot-inbox"),
        asyncio.create_task(robot.heartbeat_loop(settings.heartbeat_hz), name="heartbeat"),
    ]
    server = server_task = None
    if settings.dashboard:
        run_token = secrets.token_urlsafe(32)
        server = _build_server(settings, supervisor, robot, run_token)
        server_task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.4)
        print(f"Dashboard: http://{settings.host}:{settings.port}/#t={run_token}\n"
              "  Open it before the robot starts moving. The link is valid for this run only.")

    try:
        if not await robot.wait_online(settings.online_timeout_s):
            return "Robot is offline: no telemetry received. Is spider-body running?"
        planner.start(task)
        initial = {"task": task, "pending": [], "step": 0, "status": "running", "last_text": ""}
        config = {"configurable": {"thread_id": uuid.uuid4().hex},
                  "recursion_limit": settings.max_steps * 4 + 40}
        bus.publish("status", status="running")
        try:
            final = await asyncio.wait_for(graph.ainvoke(initial, config=config),
                                           timeout=settings.max_wall_seconds)
            summary = final.get("last_text") or "Task finished."
        except Stopped:
            summary = "Stopped by the owner."
            bus.publish("done", reason="stopped", text=summary)
        except TimeoutError:
            supervisor.stop()
            summary = f"Stopped: wall-time limit of {settings.max_wall_seconds}s reached."
            bus.publish("done", reason="timeout", text=summary)
        return summary
    finally:
        with contextlib.suppress(Exception):
            robot.stop()  # whatever happened, the robot does not keep walking
            await asyncio.sleep(0.3)
        if server is not None and server_task is not None:
            server.should_exit = True
            await server_task
        for t in background:
            t.cancel()
        with contextlib.suppress(Exception):
            await link.stop()


def _build_server(settings: Settings, supervisor: Supervisor, robot: RobotClient, token: str):
    import uvicorn

    app = create_app(supervisor, robot, run_token=token, port=settings.port,
                     extra_origins=settings.dashboard_origins,
                     token_timeout=settings.run_token_seconds)
    return uvicorn.Server(
        uvicorn.Config(app, host=settings.host, port=settings.port, log_level="warning")
    )
