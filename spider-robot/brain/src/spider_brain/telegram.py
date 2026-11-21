"""Owner-only Telegram bot for the robot brain (official Bot API, long polling, no webhook).

What the owner can do from the phone:
  - write anything (or send a voice note) -> it becomes a task: chat, knowledge (CV, Japanese
    email, advice via skills) or a robot job; the answer comes back as text (+ voice for voice)
  - /run <task>          multi-step robot task on the strong model tier
  - /status /scan        robot state and LiDAR summary
  - /photo [question]    camera photo (+ vision answer)
  - /watch on|off  /who  gesture watch and face names (perception on the home server)
  - /stand /sit /relax   posture;  /stop /estop /release  stopping;  /pause /resume /cancel
  - /memory [query]  /forget <id>
  - Approve / Reject buttons for every action that needs approval
  - alerts on obstacle stop, fall, tilt, link loss, E-stop

Rules from the JobHunt repo: only owner user ids are served; anyone else gets no reply (and is
logged). Messages are data for the planner; motion still goes through the risk policy, the
approval buttons and the robot's own reflexes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

import httpx

from .robot_client import ConfirmRefused, RobotOffline

if TYPE_CHECKING:
    from .service import BrainService

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
MAX_TEXT = 4000
HELP = (
    "Write or say anything: a question, a CV/email request, or a robot job.\n"
    "/run <task> - multi-step robot task\n"
    "/status /scan /photo [question] /who\n"
    "/watch on|off - held gestures: Stop, greet, describe, photo\n"
    "/stand /sit /relax\n"
    "/stop /estop /release /pause /resume /cancel\n"
    "/record [seconds] /map <job id>\n"
    "/memory [query] /forget <id>"
)
ALERTS = {"obstacle_stop", "fallen", "tilt", "link_lost", "estop", "offline", "health"}


class TelegramBot:
    def __init__(self, service: BrainService, token: str, owners: set[int],
                 http: httpx.AsyncClient | None = None) -> None:
        self.svc = service
        self.token = token
        self.owners = owners
        self.http = http or httpx.AsyncClient(base_url=API, timeout=45.0)
        self._approval_msgs: dict[str, list[tuple[int, int]]] = {}  # approval id -> (chat, msg)
        self._alert_at: dict[str, float] = {}
        self._task_chat: int | None = None
        self._ignored: set[int] = set()

    # ------------------------------------------------------------------ Bot API
    async def call(self, method: str, **params):
        resp = await self.http.post(f"/bot{self.token}/{method}", json=params)
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data["result"]

    async def send(self, chat: int, text: str, **extra) -> int | None:
        try:
            msg = await self.call("sendMessage", chat_id=chat, text=text[:MAX_TEXT], **extra)
            return msg.get("message_id")
        except (httpx.HTTPError, RuntimeError) as exc:
            log.warning("Telegram send failed: %s", exc)
            return None

    async def _upload(self, method: str, chat: int, field: str, name: str, data: bytes,
                      mime: str, caption: str = "", reply_markup: dict | None = None) -> None:
        form = {"chat_id": str(chat), "caption": caption[:1000]}
        if reply_markup is not None:
            form["reply_markup"] = json.dumps(reply_markup)
        try:
            resp = await self.http.post(
                f"/bot{self.token}/{method}",
                data=form,
                files={field: (name, data, mime)},
            )
            if not resp.json().get("ok"):
                log.warning("Telegram %s failed: %s", method, resp.text[:200])
        except httpx.HTTPError as exc:
            log.warning("Telegram %s failed: %s", method, exc)

    @staticmethod
    def _watch_text(watcher) -> str:
        gestures = ", ".join(f"{g}: {a}" for g, a in sorted(watcher.actions.items()))
        return (f"Watch {'on' if watcher.on else 'off'}: {watcher.remaining_s / 60:.0f} min left.\n"
                f"Gestures: {gestures}")

    async def send_owner_photo(self, jpeg: bytes, caption: str = "") -> None:
        for owner in self.owners:
            await self._upload("sendPhoto", owner, "photo", "watch.jpg", jpeg, "image/jpeg",
                               caption=caption)

    async def _download(self, file_id: str) -> bytes:
        info = await self.call("getFile", file_id=file_id)
        resp = await self.http.get(f"/file/bot{self.token}/{info['file_path']}")
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------ loops
    async def run(self) -> None:
        offset = None
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ["message", "callback_query"]}
                if offset is not None:
                    params["offset"] = offset
                updates = await self.call("getUpdates", **params)
            except (httpx.HTTPError, RuntimeError) as exc:
                log.warning("Telegram polling error: %s", exc)
                await asyncio.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                # each update in its own task: an approval button must work while a task runs
                asyncio.create_task(self._safe_handle(u))

    async def _safe_handle(self, update: dict) -> None:
        try:
            await self.handle(update)
        except Exception:
            log.exception("Telegram update failed")

    async def notify_loop(self) -> None:
        async for ev in self.svc.bus.subscribe():
            kind = ev.get("kind")
            if kind == "approval_request":
                await self._ask_approval(ev)
            elif kind == "approval_resolved":
                await self._close_approval(ev)
            elif kind == "robot_event" and ev.get("event") in ALERTS:
                await self._alert(ev)
            elif kind == "camera" and self._task_chat is not None:
                import base64

                await self._upload("sendPhoto", self._task_chat, "photo", "photo.jpg",
                                   base64.b64decode(ev["data"]), "image/jpeg")

    # ------------------------------------------------------------------ updates
    async def handle(self, update: dict) -> None:
        if "callback_query" in update:
            await self._callback(update["callback_query"])
            return
        msg = update.get("message")
        if not msg:
            return
        uid = (msg.get("from") or {}).get("id")
        chat = msg["chat"]["id"]
        if uid not in self.owners:
            if uid not in self._ignored:
                self._ignored.add(uid)
                log.warning("ignoring Telegram user %s (not an owner)", uid)
            return  # no reply to strangers
        text = (msg.get("text") or msg.get("caption") or "").strip()
        from_voice = False
        audio = msg.get("voice") or msg.get("audio")
        if audio:
            if self.svc.voice is None:
                await self.send(chat, "Voice is not configured (GEMINI_API_KEY).")
                return
            try:
                data = await self._download(audio["file_id"])
                text = await self.svc.voice.transcribe(data, audio.get("mime_type", "audio/ogg"))
            except Exception as exc:
                await self.send(chat, f"I couldn't understand the voice note: {exc}")
                return
            if not text:
                await self.send(chat, "I heard no speech in that voice note.")
                return
            await self.send(chat, f"🎤 {text}")
            from_voice = True
        if not text:
            return
        if text.startswith("/"):
            await self.command(chat, text)
        else:
            await self.task(chat, text, tier="simple", voice_reply=from_voice)

    async def command(self, chat: int, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        robot = self.svc.robot
        try:
            if cmd in ("/start", "/help"):
                await self.send(chat, HELP)
            elif cmd == "/status":
                await self.send(chat, robot.status_text())
            elif cmd == "/scan":
                await self.send(chat, robot.surroundings_text())
            elif cmd == "/photo":
                jpeg = await robot.snapshot()
                answer = ""
                if arg and self.svc.vision is not None:
                    answer = await self.svc.vision.ask(jpeg, arg)
                await self._upload("sendPhoto", chat, "photo", "photo.jpg", jpeg, "image/jpeg",
                                   caption=answer)
            elif cmd == "/watch":
                watcher = self.svc.watcher
                if watcher is None:
                    await self.send(chat, "Perception is off on the home server.")
                elif arg.strip().lower() == "on":
                    watcher.turn_on()
                    await self.send(chat, self._watch_text(watcher))
                elif arg.strip().lower() == "off":
                    watcher.turn_off()
                    await self.send(chat, "Watch off.")
                else:
                    await self.send(chat, "Usage: /watch on or /watch off")
            elif cmd == "/who":
                if self.svc.perception is None:
                    await self.send(chat, "Perception is off on the home server.")
                else:
                    from .perception import decode_jpeg

                    jpeg = await robot.snapshot(timeout_s=3.0, human=True)
                    frame = decode_jpeg(jpeg)
                    who = await self.svc.perception.run(self.svc.perception.who, frame)
                    await self._upload("sendPhoto", chat, "photo", "who.jpg", jpeg,
                                       "image/jpeg", caption=who)
            elif cmd in ("/stand", "/sit", "/relax"):
                posture = cmd[1:]
                if self.svc.confirm.needs_wake(posture):
                    await self._confirm(chat, "wake_from_limp", posture)
                else:
                    await self.send(chat, await robot.posture(posture, human=True))
            elif cmd == "/stop":
                robot.cancel_motion()
                await self.send(chat, "Stop sent.")
            elif cmd == "/estop":
                robot.estop()
                robot.cancel_motion()
                self.svc.supervisor.stop()
                await self.send(chat, "E-STOP latched. /release to unlatch.")
            elif cmd == "/release":
                if robot.via_gateway:
                    await self._confirm(chat, "estop_release")
                else:
                    robot.estop_release()
                    await self.send(chat, "E-stop released.")
            elif cmd == "/record":
                seconds = float(arg) if arg.strip().replace(".", "", 1).isdigit() else 60.0
                seconds = max(1.0, min(3600.0, seconds))
                job = self.svc.jobs.start_recording(seconds)
                await self.send(chat, f"Recording {job}, {seconds:.0f} s. /map {job} afterwards.")
            elif cmd == "/map":
                job = arg.strip()
                if not job:
                    await self.send(chat, "Usage: /map <job id>")
                else:
                    await self.send(chat, f"Processing {job}. The worker stops itself when done.")
                    await self.send(chat, await self.svc.jobs.process(job))
            elif cmd == "/pause":
                robot.cancel_motion()
                self.svc.supervisor.pause()
                await self.send(chat, "Paused. /resume to continue.")
            elif cmd == "/resume":
                self.svc.supervisor.resume()
                await self.send(chat, "Resumed.")
            elif cmd == "/cancel":
                robot.cancel_motion()
                self.svc.supervisor.stop()
                await self.send(chat, "Task cancelled.")
            elif cmd == "/run":
                if not arg:
                    await self.send(chat, "Usage: /run <task>")
                else:
                    await self.task(chat, arg, tier="default", voice_reply=False)
            elif cmd == "/memory":
                facts = self.svc.memory.recall(arg)
                await self.send(chat, "\n".join(f"#{f.id}: {f.text}" for f in facts) or "Empty.")
            elif cmd == "/forget":
                ok = arg.strip().isdigit() and self.svc.memory.forget(int(arg))
                await self.send(chat, "Forgotten." if ok else "Usage: /forget <id>")
            else:
                await self.send(chat, HELP)
        except RobotOffline as exc:
            await self.send(chat, f"Robot offline: {exc}")

    async def task(self, chat: int, text: str, tier: str, voice_reply: bool) -> None:
        from .service import Busy

        if self.svc.busy:
            await self.send(chat, f"Busy with: {self.svc.current_task}\n/cancel to stop it.")
            return
        self._task_chat = chat
        try:
            summary = await self.svc.run_task(text, tier=tier)
        except Busy as exc:
            await self.send(chat, f"Busy with: {exc}")
            return
        finally:
            self._task_chat = None
        await self.send(chat, summary)
        if voice_reply and self.svc.settings.voice_replies and self.svc.voice is not None:
            audio = await self.svc.voice.speak(summary)
            if audio is not None:
                data, fmt = audio
                if fmt == "ogg":
                    await self._upload("sendVoice", chat, "voice", "reply.ogg", data, "audio/ogg")
                else:
                    await self._upload("sendAudio", chat, "audio", "reply.mp3", data, "audio/mpeg")

    # ------------------------------------------------------------------ confirmed actions
    async def _confirm(self, chat: int, action: str, posture: str | None = None) -> None:
        """The owner sees a frame taken just now and confirms that exact frame."""
        try:
            conf = await self.svc.confirm.begin(action, posture)
        except ConfirmRefused as exc:
            await self.send(chat, f"Refused: {exc}")
            return
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Clear, go ahead", "callback_data": f"cf:{conf.id}:1"},
            {"text": "❌ Cancel", "callback_data": f"cf:{conf.id}:0"},
        ]]}
        await self._upload("sendPhoto", chat, "photo", "confirm.jpg", conf.jpeg, "image/jpeg",
                           caption=f"{action}: is the robot clear? Expires in {conf.ttl_s:.0f} s.",
                           reply_markup=keyboard)

    # ------------------------------------------------------------------ approvals and alerts
    async def _ask_approval(self, ev: dict) -> None:
        keyboard = {"inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"ap:{ev['id']}:1"},
            {"text": "❌ Reject", "callback_data": f"ap:{ev['id']}:0"},
        ]]}
        sent = []
        for owner in self.owners:
            mid = await self.send(owner, f"Approve? [{ev.get('risk')}] {ev.get('description')}",
                                  reply_markup=keyboard)
            if mid is not None:
                sent.append((owner, mid))
        self._approval_msgs[ev["id"]] = sent

    async def _close_approval(self, ev: dict) -> None:
        verdict = "✅ approved" if ev.get("approved") else "❌ rejected"
        for chat, mid in self._approval_msgs.pop(ev["id"], []):
            try:
                await self.call("editMessageReplyMarkup", chat_id=chat, message_id=mid,
                                reply_markup={"inline_keyboard": []})
                await self.send(chat, verdict, reply_to_message_id=mid)
            except (httpx.HTTPError, RuntimeError):
                pass

    async def _callback(self, cq: dict) -> None:
        uid = (cq.get("from") or {}).get("id")
        if uid not in self.owners:
            return
        parts = str(cq.get("data", "")).split(":")
        if len(parts) == 3 and parts[0] == "ap":
            self.svc.supervisor.decide(parts[1], parts[2] == "1")
        elif len(parts) == 3 and parts[0] == "cf":
            done = self.svc.confirm.resolve(parts[1], parts[2] == "1")
            chat = (cq.get("message") or {}).get("chat", {}).get("id")
            if chat is not None:
                text = "Sent." if done and parts[2] == "1" else "Cancelled or expired."
                await self.send(chat, text)
        try:
            await self.call("answerCallbackQuery", callback_query_id=cq["id"])
        except (httpx.HTTPError, RuntimeError):
            pass

    async def _alert(self, ev: dict) -> None:
        kind = ev["event"]
        now = time.monotonic()
        if now - self._alert_at.get(kind, -1e9) < 10.0:
            return
        self._alert_at[kind] = now
        for owner in self.owners:
            await self.send(owner, f"⚠️ {kind}: {ev.get('detail', '')}".strip())
