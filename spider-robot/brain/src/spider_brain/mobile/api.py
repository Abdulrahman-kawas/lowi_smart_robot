"""HTTP and WebSocket routes of the mobile API, under /v1 on the dashboard's loopback port.

Reach it only through `tailscale serve`. Every route but /v1/hello and /v1/pair needs
"Authorization: Bearer <device token>"; the WebSocket takes the token as its first message.
(No `from __future__ import annotations` here: FastAPI resolves these annotations at runtime.)
"""

import asyncio
import base64
import binascii
import contextlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..robot_client import ConfirmRefused, RobotOffline
from .devices import RateLimited, clean_name
from .hub import API_VERSION, Busy, MobileHub, Session
from .talk import TalkError

AUTH_TIMEOUT_S = 5.0
SOCKET_SILENCE_S = 3.0  # the app sends a heartbeat every second
CLOSE_BAD_TOKEN = 4401
CLOSE_BROWSER = 4403  # the app sends no Origin header; a browser always does


class PairBody(BaseModel):
    code: str = Field(max_length=16)
    device_name: str = Field(max_length=200)


class ConfirmBody(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    approved: bool


class WakeBody(BaseModel):
    posture: Literal["stand", "sit"] = "stand"


class PhotoBody(BaseModel):
    question: str | None = Field(None, max_length=500)


class TalkBody(BaseModel):
    # 16 kHz mono 16-bit WAV: 60 s (the highest SB_TALK_MAX_S) is 1.92 MB, 2.56 MB in base64
    audio_b64: str = Field(min_length=8, max_length=2_600_000)
    mime: Literal["audio/wav", "audio/x-wav", "audio/wave"] = "audio/wav"


def build_router(hub: MobileHub) -> APIRouter:
    router = APIRouter(prefix="/v1")

    def device(authorization: Annotated[str | None, Header()] = None) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        name = hub.devices.check(token.strip()) if scheme.lower() == "bearer" else None
        if name is None:
            raise HTTPException(401, "missing or bad token",
                                headers={"WWW-Authenticate": "Bearer"})
        return name

    Device = Annotated[str, Depends(device)]

    @router.get("/hello")
    async def hello() -> dict:
        return {"service": "spider-brain", "api": API_VERSION}

    @router.post("/pair")
    async def pair(body: PairBody) -> dict:
        name = clean_name(body.device_name)
        if name is None:
            raise HTTPException(400, "device name: 1 to 40 printable characters")
        try:
            ok = hub.codes.redeem(body.code)
        except RateLimited as exc:
            raise HTTPException(429, str(exc)) from exc
        if not ok:
            raise HTTPException(401, "the pairing code is wrong, used or expired")
        return {"token": hub.devices.add(name), "device_name": name,
                "robot_id": hub.robot_id, "caps": hub.caps_view()}

    @router.get("/state")
    async def state(_: Device) -> dict:
        return hub.state_view()

    @router.post("/stop")
    async def stop(who: Device) -> dict:
        return {"sent": hub.stop(who) >= 0}

    @router.post("/estop")
    async def estop(who: Device) -> dict:
        return {"sent": hub.estop(who) >= 0}

    @router.post("/estop/release")
    async def estop_release(who: Device) -> dict:
        st = hub.robot.state
        if st is None:
            raise HTTPException(503, "robot offline: no telemetry yet")
        if not st.estop:
            raise HTTPException(409, "the E-stop is not latched")
        try:
            return await hub.begin_confirm(who, "estop_release")
        except ConfirmRefused as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/wake")
    async def wake(who: Device, body: WakeBody) -> dict:
        if not hub.confirm.needs_wake(body.posture):
            raise HTTPException(409, "the robot is not limp; send the posture directly")
        try:
            return await hub.begin_confirm(who, "wake_from_limp", body.posture)
        except ConfirmRefused as exc:
            raise HTTPException(503, str(exc)) from exc

    @router.post("/confirm")
    async def confirm(who: Device, body: ConfirmBody) -> dict:
        result = await hub.finish_confirm(who, body.challenge_id, body.approved)
        if result is None:
            raise HTTPException(409, "unknown, used or expired confirmation")
        return result

    @router.post("/photo")
    async def photo(who: Device, body: PhotoBody | None = None) -> dict:
        question = (body.question or "").strip() if body is not None else ""
        try:
            return await hub.photo(question or None)
        except Busy as exc:
            raise HTTPException(429, str(exc)) from exc
        except RobotOffline as exc:
            raise HTTPException(503, f"robot offline: {exc}") from exc
        except (TimeoutError, RuntimeError) as exc:
            raise HTTPException(504, f"no camera frame: {exc or 'timed out'}") from exc

    @router.post("/talk")
    async def talk(who: Device, body: TalkBody) -> dict:
        """Hold to talk: speech in, a text answer out. A stop word sends STOP; nothing moves."""
        try:
            audio = base64.b64decode(body.audio_b64, validate=True)
        except binascii.Error as exc:
            raise HTTPException(400, "audio_b64 is not valid base64") from exc
        try:
            return await hub.talk.run(who, audio)
        except TalkError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @router.websocket("/live")
    async def live(socket: WebSocket) -> None:
        await socket.accept()
        if socket.headers.get("origin"):
            await socket.close(code=CLOSE_BROWSER)
            return
        try:
            first = await asyncio.wait_for(socket.receive_json(), AUTH_TIMEOUT_S)
        except (TimeoutError, ValueError, KeyError, RuntimeError, WebSocketDisconnect):
            with contextlib.suppress(RuntimeError):
                await socket.close(code=CLOSE_BAD_TOKEN)
            return
        who = (hub.devices.check(first.get("token"))
               if isinstance(first, dict) and first.get("type") == "auth" else None)
        if who is None:
            await socket.close(code=CLOSE_BAD_TOKEN)
            return
        session = hub.connect(who)
        tasks = {asyncio.create_task(hub.send(session, socket)),
                 asyncio.create_task(_receive(hub, session, socket)),
                 asyncio.create_task(session.closing.wait())}
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            hub.disconnect(session)  # first: a driving device stops the robot here
            for task in tasks:
                task.cancel()
            with contextlib.suppress(Exception):
                await socket.close(code=session.close_code or 1000)

    return router


async def _receive(hub: MobileHub, session: Session, socket: WebSocket) -> None:
    """Returns when the socket closes or goes silent; the caller then disconnects the session."""
    while True:
        try:
            msg = await asyncio.wait_for(socket.receive(), SOCKET_SILENCE_S)
        except TimeoutError:
            return
        if msg["type"] == "websocket.disconnect":
            return
        text = msg.get("text")
        if text is None:
            continue
        try:
            data = json.loads(text)
        except ValueError:
            hub.handle(session, None)
            continue
        hub.handle(session, data)
