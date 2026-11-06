"""Remote supervision dashboard: one page + one websocket (pattern from desktop-agent).

Security (same as desktop-agent D1/D2):
  * binds to loopback only; reach it through an SSM/SSH tunnel or `tailscale serve`
  * websocket requires an allowed Origin AND a per-run token as the first message
Robot buttons (E-STOP, release, stop) work even while the agent is paused or waiting.
"""

from __future__ import annotations

import asyncio
import hmac
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from ..robot_client import RobotClient
from .supervisor import Supervisor

_INDEX = (Path(__file__).parent / "static" / "index.html").read_text("utf-8")

CLOSE_BAD_ORIGIN = 4403
CLOSE_BAD_TOKEN = 4401


def allowed_origins(port: int, extra: list[str]) -> frozenset[str]:
    local = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    return frozenset(local | {o.rstrip("/") for o in extra})


def create_app(
    supervisor: Supervisor,
    robot: RobotClient,
    *,
    run_token: str,
    port: int,
    extra_origins: list[str] | None = None,
    token_timeout: float = 5.0,
) -> FastAPI:
    app = FastAPI(title="Spider Brain")
    origins = allowed_origins(port, extra_origins or [])

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _INDEX

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        if socket.headers.get("origin", "").rstrip("/") not in origins:
            await socket.close(code=CLOSE_BAD_ORIGIN)
            return
        try:
            hello = await asyncio.wait_for(socket.receive_json(), timeout=token_timeout)
        except (TimeoutError, ValueError, WebSocketDisconnect):
            await socket.close(code=CLOSE_BAD_TOKEN)
            return
        presented = hello.get("token", "") if isinstance(hello, dict) else ""
        if not isinstance(presented, str) or not hmac.compare_digest(presented, run_token):
            await socket.close(code=CLOSE_BAD_TOKEN)
            return

        async def pump_events() -> None:
            async for event in supervisor.bus.subscribe():
                await socket.send_json(event)

        async def pump_commands() -> None:
            while True:
                handle(supervisor, robot, await socket.receive_json())

        sender = asyncio.create_task(pump_events())
        receiver = asyncio.create_task(pump_commands())
        try:
            await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            receiver.cancel()

    return app


def handle(supervisor: Supervisor, robot: RobotClient, msg: dict) -> None:
    cmd = msg.get("cmd") if isinstance(msg, dict) else None
    # Every stopping button cancels the running walk/turn first; otherwise the tool would keep
    # renewing Move commands and the robot would keep walking (only E-STOP would work).
    if cmd == "estop":
        robot.estop()
        robot.cancel_motion()
        supervisor.stop()
    elif cmd == "estop_release":
        robot.estop_release()
    elif cmd == "robot_stop":
        robot.cancel_motion()
    elif cmd == "pause":
        robot.cancel_motion()
        supervisor.pause()
    elif cmd == "resume":
        supervisor.resume()
    elif cmd == "stop":
        robot.cancel_motion()
        supervisor.stop()
    elif cmd == "decide" and isinstance(msg.get("id"), str):
        supervisor.decide(msg["id"], bool(msg.get("approved")))
