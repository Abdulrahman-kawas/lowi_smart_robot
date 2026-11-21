"""BrainService: the long-running brain.

One process keeps everything alive: the robot link, the dashboard, the Telegram bot, WhatsApp
alerts, skills, memory, vision and voice. Tasks (from the CLI, Telegram text or voice) run one
at a time through the same LangGraph loop as before, with a fresh planner per task and the
same Supervisor (pause / stop / approvals) shared by the dashboard and Telegram.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import uuid
from collections.abc import Callable
from pathlib import Path

from spider_common.link import Link
from spider_common.obs import new_trace
from spider_common.protocol import MAX_SAY_CHARS, SayRequest

from .config import Settings
from .confirm import ConfirmFlow
from .graph import build_graph
from .jobs import AwsWorker, JobManager
from .memory import Memory
from .observe import HealthMonitor, TraceStore
from .planner import Planner, make_planner
from .robot_client import RobotClient, RobotOffline
from .skills import SkillLibrary
from .supervision.events import EventBus
from .supervision.server import create_app
from .supervision.supervisor import Stopped, Supervisor
from .tools import ToolExecutor
from .vision import make_vision
from .voice import VoiceService
from .whatsapp import WhatsAppNotifier
from .workers import AskService, SttWorker, make_chat_chain

log = logging.getLogger(__name__)

BRAIN_ROOT = Path(__file__).resolve().parents[2]  # spider-robot/brain
ALERT_EVENTS = {"obstacle_stop", "fallen", "tilt", "link_lost", "estop", "offline", "health"}


class TaskSupervisor(Supervisor):
    """desktop-agent's Supervisor, reusable across tasks (the dashboard keeps one object)."""

    def reset(self) -> None:
        self._stop = asyncio.Event()
        self._resumed.set()
        self._approvals.clear()
        self.status = "running"


class Busy(RuntimeError):
    pass


def resolve_dirs(dirs: list[str]) -> list[Path]:
    out = []
    for d in dirs:
        p = Path(d).expanduser()
        out.append(p if p.is_absolute() else (BRAIN_ROOT / p).resolve())
    return out


class BrainService:
    def __init__(
        self,
        settings: Settings,
        *,
        link: Link | None = None,
        vision=None,
        voice: VoiceService | None = None,
        planner_factory: Callable[[str], Planner] | None = None,
        telegram_http=None,
        whatsapp_http=None,
        role: str = "serve",
    ) -> None:
        from .runner import build_link  # local import: runner imports this module

        self.settings = settings
        self.bus = EventBus()
        self.supervisor = TaskSupervisor(self.bus)
        self.link = link or build_link(settings, role)
        self.robot = RobotClient(self.link, settings.robot_id, self.bus, settings.robot_source,
                                 settings.human_source)
        self.confirm = ConfirmFlow(self.robot, self.bus)
        traces_path = Path(settings.traces_path).expanduser()
        self.traces = TraceStore(traces_path if traces_path.is_absolute()
                                 else BRAIN_ROOT / traces_path)
        self.health = HealthMonitor(self.bus)
        self.jobs = JobManager(self.robot, settings, AwsWorker.from_settings(settings))
        self.vision = vision if vision is not None else make_vision(settings)
        self.skills = SkillLibrary(resolve_dirs(settings.skills_dirs), settings.always_on_skills)
        mem_path = Path(settings.memory_path).expanduser()
        self.memory = Memory(mem_path if mem_path.is_absolute() else BRAIN_ROOT / mem_path)
        self.executor = ToolExecutor(self.robot, self.vision, settings, self.bus,
                                     self.skills, self.memory)
        self.voice = voice if voice is not None else (
            VoiceService(settings) if settings.gemini_api_key else None)
        self.perception = None
        if settings.perception:
            from .perception import make_perception

            self.perception = make_perception(settings)
        self.ask = (
            AskService(self.link, settings, self.robot, self.vision, make_chat_chain(settings),
                       perception=self.perception)
            if settings.ask_worker else None
        )
        self.stt = SttWorker(self.link, settings) if settings.stt_worker else None
        self._attach_handlers()
        self._planner_factory = planner_factory or (
            lambda tier: make_planner(settings, tier, self.skills.system_text(), self.context))
        self._lock = asyncio.Lock()
        self.current_task: str | None = None
        self._bg: list[asyncio.Task] = []
        self._server = None
        self.run_token = secrets.token_urlsafe(32)
        self.whatsapp = (
            WhatsAppNotifier(settings.whatsapp_bridge_url, settings.whatsapp_bridge_token,
                             http=whatsapp_http)
            if settings.whatsapp_bridge_url else None
        )
        self.mobile = None
        if settings.mobile:
            from .mobile.devices import data_dir
            from .mobile.hub import MobileHub

            self.mobile = MobileHub(self, data_dir(settings.mobile_data_dir))
        self.telegram = None
        if settings.telegram_enabled:
            from .telegram import TelegramBot

            self.telegram = TelegramBot(self, settings.telegram_token,
                                        set(settings.telegram_owner_ids), http=telegram_http)

    def _attach_handlers(self) -> None:
        t = self.robot.topics
        self.robot.handlers += [
            (t.voice_turn, self._on_trace),
            (t.health_filter, self._on_health),
            (t.gateway_status, self._on_gateway_status),
            (t.record_event, self.jobs.on_status),
        ]
        if self.ask is not None:
            self.robot.handlers.append((t.rpc_request("ask"), self.ask.on_request))
        if self.stt is not None:
            self.robot.handlers.append((t.rpc_request("stt"), self.stt.on_request))

    def _on_trace(self, _topic: str, payload: bytes) -> None:
        self.bus.publish("latency", summary=self.traces.add(payload))

    def _on_health(self, _topic: str, payload: bytes) -> None:
        self.health.on_report(payload)

    def _on_gateway_status(self, _topic: str, payload: bytes) -> None:
        self.bus.publish("gateway_status", status=json.loads(payload))

    def say_on_robot(self, text: str) -> bool:
        """Ask the Pi voice to speak one short line. Text only: no path to a motion command."""
        clean = text.strip()
        if not clean:
            return False
        req = SayRequest(trace=new_trace(), text=clean[:MAX_SAY_CHARS])
        return self.link.publish(self.robot.topics.voice_say, req.model_dump_json(), qos=0)

    # ------------------------------------------------------------------ lifecycle
    def context(self) -> str:
        try:
            return self.robot.status_text()
        except RobotOffline as exc:
            return f"Robot offline: {exc}"

    async def start(self) -> None:
        await self.link.start()
        self._bg += [
            asyncio.create_task(self.robot.run(), name="robot-inbox"),
            asyncio.create_task(self.robot.heartbeat_loop(self.settings.heartbeat_hz),
                                name="heartbeat"),
        ]
        if self.settings.dashboard or self.mobile is not None:
            self._server = self._build_server()
            self._bg.append(asyncio.create_task(self._server.serve(), name="http"))
            await asyncio.sleep(0.4)
            if self.settings.dashboard:
                print(f"Dashboard: http://{self.settings.host}:{self.http_port}/#t={self.run_token}")
        if self.mobile is not None:
            self._bg += self.mobile.start()
            print(f"Mobile API: http://{self.settings.host}:{self.http_port}/v1 "
                  "(publish it with `tailscale serve`)")
        if self.telegram is not None:
            self._bg += [asyncio.create_task(self.telegram.run(), name="telegram"),
                         asyncio.create_task(self.telegram.notify_loop(), name="telegram-notify")]
        if self.whatsapp is not None:
            self._bg.append(asyncio.create_task(self._whatsapp_loop(), name="whatsapp"))

    async def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.robot.stop()  # whatever happened, the robot does not keep walking
            await asyncio.sleep(0.3)
        if self._server is not None:
            self._server.should_exit = True
        for t in self._bg:
            t.cancel()
        await asyncio.gather(*self._bg, return_exceptions=True)
        if self.perception is not None:
            self.perception.close()
        with contextlib.suppress(Exception):
            await self.link.stop()

    @property
    def http_port(self) -> int:
        """The port the dashboard and mobile API listen on (the real one when SB_PORT=0)."""
        servers = getattr(self._server, "servers", None)
        if servers and servers[0].sockets:
            return servers[0].sockets[0].getsockname()[1]
        return self.settings.port

    def _build_server(self):
        import uvicorn
        from fastapi import FastAPI

        if self.settings.dashboard:
            app = create_app(self.supervisor, self.robot, run_token=self.run_token,
                             port=self.settings.port,
                             extra_origins=self.settings.dashboard_origins,
                             token_timeout=self.settings.run_token_seconds, confirm=self.confirm)
        else:
            app = FastAPI(title="Spider Brain")
        if self.mobile is not None:
            from .mobile.api import build_router

            app.include_router(build_router(self.mobile))
        return uvicorn.Server(uvicorn.Config(app, host=self.settings.host,
                                             port=self.settings.port, log_level="warning"))

    async def _whatsapp_loop(self) -> None:
        assert self.whatsapp is not None
        async for ev in self.bus.subscribe():
            if ev.get("kind") == "robot_event" and ev.get("event") in ALERT_EVENTS:
                await self.whatsapp.alert(f"Robot {self.settings.robot_id}: {ev['event']} "
                                          f"{ev.get('detail', '')}".strip(), ev["event"])

    # ------------------------------------------------------------------ tasks
    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def run_task(
        self, task: str, tier: str = "default", planner: Planner | None = None,
        require_robot: bool = False,
    ) -> str:
        if self._lock.locked():
            raise Busy(self.current_task or "another task")
        async with self._lock:
            self.current_task = task
            try:
                return await self._run(task, tier, planner, require_robot)
            finally:
                self.current_task = None

    async def _run(self, task: str, tier: str, planner: Planner | None,
                   require_robot: bool) -> str:
        s = self.settings
        online = await self.robot.wait_online(s.online_timeout_s if require_robot else 2.0)
        if require_robot and not online:
            return "Robot is offline: no telemetry received. Is spider-body running?"
        self.supervisor.reset()
        planner = planner or self._planner_factory(tier)
        planner.start(task)
        graph = build_graph(s, planner, self.executor, self.supervisor)
        initial = {"task": task, "pending": [], "step": 0, "status": "running", "last_text": ""}
        config = {"configurable": {"thread_id": uuid.uuid4().hex},
                  "recursion_limit": s.max_steps * 4 + 40}
        self.bus.publish("status", status="running")
        self.bus.publish("task_started", task=task[:200], tier=tier)
        try:
            final = await asyncio.wait_for(graph.ainvoke(initial, config=config),
                                           timeout=s.max_wall_seconds)
            summary = final.get("last_text") or "Task finished."
        except Stopped:
            summary = "Stopped by the owner."
            self.bus.publish("done", reason="stopped", text=summary)
        except TimeoutError:
            self.supervisor.stop()
            summary = f"Stopped: wall-time limit of {s.max_wall_seconds}s reached."
            self.bus.publish("done", reason="timeout", text=summary)
        finally:
            with contextlib.suppress(Exception):
                self.robot.stop()
        cost = getattr(planner, "cost_usd", 0.0)
        self.bus.publish("task_finished", text=summary, cost_usd=round(cost, 4))
        return summary
