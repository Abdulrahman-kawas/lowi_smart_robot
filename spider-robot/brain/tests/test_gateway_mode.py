"""The brain, the real gateway and the simulated body working together."""

import asyncio
import base64
import time
from pathlib import Path

import httpx
import pytest
from spider_body.config import load_config
from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank
from spider_body.main import command_loop, control_loop, state_loop
from spider_body.robot import Robot
from spider_common.link import InMemoryHub
from spider_common.protocol import (
    AskReply,
    AskRequest,
    HealthReport,
    Posture,
    RobotEvent,
    SttReply,
    SttRequest,
    Topics,
    VoiceTurn,
)
from spider_gateway.gateway import Gateway

from spider_brain.config import Settings
from spider_brain.confirm import ConfirmFlow
from spider_brain.observe import HealthMonitor, TraceStore, assess
from spider_brain.robot_client import ConfirmRefused, RobotClient
from spider_brain.supervision.events import EventBus
from spider_brain.supervision.server import handle
from spider_brain.supervision.supervisor import Supervisor
from spider_brain.vision import CompatVision, RoutedVision, make_vision
from spider_brain.workers import AskService, ChatClient, SttWorker, make_chat_chain

ROBOT = "spider-01"
T = Topics(ROBOT)
SIM_CFG = Path(__file__).resolve().parents[2] / "body" / "config" / "robot.sim.yaml"


def settings(**kw) -> Settings:
    return Settings(_env_file=None, dashboard=False, **kw)


async def _until(condition, timeout_s):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
async def world():
    cfg = load_config(SIM_CFG, calibration="/nonexistent")
    cfg.gait.posture_speed_mps = 0.2
    hub = InMemoryHub()
    sim = SimWorld(obstacles=[])
    body_link = hub.endpoint([T.cmd])
    robot = Robot(cfg, FakeServoBank(), SimLidar(cfg.lidar, sim), FakeCamera(cfg.camera), body_link)
    gw_link = hub.endpoint(Gateway.subscriptions(ROBOT))
    gateway = Gateway(gw_link, ROBOT)
    brain_link = hub.endpoint(RobotClient.subscriptions(ROBOT, "planner", "remote"))
    voice = hub.endpoint([T.source_event("voice")])
    for link in (body_link, gw_link, brain_link, voice):
        await link.start()
    client = RobotClient(brain_link, ROBOT, EventBus(), "planner", "remote")

    async def voice_beat():
        from spider_common.protocol import Heartbeat

        while True:
            voice.publish(T.request("voice"), Heartbeat(ts=time.time()).model_dump_json())
            await asyncio.sleep(0.1)

    tasks = [asyncio.create_task(c) for c in (
        control_loop(robot, sim), command_loop(robot, body_link), state_loop(robot, body_link),
        robot.lidar.run(), gateway.run(tick_hz=20.0), client.run(), client.heartbeat_loop(10.0),
        voice_beat())]
    await client.wait_online(5.0)
    yield robot, gateway, client, voice
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def stand(robot, voice):
    voice.publish(T.request("voice"), Posture(seq=1, session="v", ts=time.time(),
                                              posture="stand").model_dump_json())
    assert await _until(lambda: robot.mode == "standing" and robot._height_reached(), 15.0)


async def test_voice_stop_ends_a_planner_walk_for_good(world):
    from spider_common.protocol import Stop

    robot, gateway, client, voice = world
    await stand(robot, voice)
    await asyncio.sleep(2.2)  # the pose hold from voice has passed
    walk = asyncio.create_task(client.walk("forward", 1.0, 0.05, "tripod"))
    assert await _until(lambda: robot.move is not None, 3.0)
    voice.publish(T.request("voice"), Stop(seq=2, session="v", ts=time.time()).model_dump_json())
    result = await asyncio.wait_for(walk, 8.0)
    assert result.stopped_by is not None and "preempted" in result.stopped_by
    await asyncio.sleep(0.8)  # would be renewed within 0.5 s if the defect were still there
    assert robot.move is None


async def test_remote_estop_release_through_the_real_stack(world):
    robot, gateway, client, voice = world
    await stand(robot, voice)
    client.estop()
    assert await _until(lambda: robot.estop, 2.0)
    await asyncio.sleep(0.3)
    client.estop_release()  # no frame, no release
    await asyncio.sleep(0.2)
    assert robot.estop
    conf = await client.request_confirm("estop_release")
    assert conf.jpeg[:2] == b"\xff\xd8"
    client.estop_release(conf)
    assert await _until(lambda: not robot.estop, 2.0)


async def test_confirm_flow_publishes_the_frame_and_resolves_once(world):
    robot, gateway, client, voice = world
    await stand(robot, voice)
    client.estop()
    assert await _until(lambda: robot.estop, 2.0)
    await asyncio.sleep(0.3)
    bus = EventBus()
    flow = ConfirmFlow(client, bus)
    conf = await flow.begin("estop_release")
    assert any(e["kind"] == "confirm_request" for e in bus._history)
    assert flow.resolve(conf.id, True) and not flow.resolve(conf.id, True)
    assert await _until(lambda: not robot.estop, 2.0)


async def test_denied_confirmation_sends_nothing(world):
    robot, gateway, client, voice = world
    await stand(robot, voice)
    client.estop()
    assert await _until(lambda: robot.estop, 2.0)
    await asyncio.sleep(0.3)
    flow = ConfirmFlow(client, EventBus())
    conf = await flow.begin("estop_release")
    flow.resolve(conf.id, False)
    await asyncio.sleep(0.3)
    assert robot.estop


async def test_remote_wake_from_limp_needs_confirmation(world):
    robot, gateway, client, voice = world
    await asyncio.sleep(0.4)  # the gateway has seen a state with mode=relaxed
    reply = await client.posture("stand", human=True)
    assert "Rejected" in reply and robot.mode == "relaxed"
    conf = await client.request_confirm("wake_from_limp")
    client.posture_confirmed("stand", conf)
    assert await _until(lambda: robot.mode == "standing", 3.0)


async def test_confirmation_refused_when_a_frame_does_not_match():
    hub = InMemoryHub()
    link = hub.endpoint(RobotClient.subscriptions(ROBOT, "planner", "remote"))
    gw = hub.endpoint([T.request_filter])
    await link.start()
    await gw.start()
    client = RobotClient(link, ROBOT, source="planner", human_source="remote")
    from spider_common.protocol import ConfirmChallenge, ConfirmRequest, RobotState

    client._on_state(RobotState(robot_id=ROBOT, mode="standing"))
    pump = asyncio.create_task(client.run())

    async def fake_gateway():
        msg = await asyncio.wait_for(anext(gw.messages()), 2)
        req = ConfirmRequest.model_validate_json(msg.payload)
        body = ConfirmChallenge(id="c", action=req.action, request_id=req.request_id,
                                sha256="0" * 64, ttl_s=30)
        gw.publish(T.camera(req.request_id), b"different")
        gw.publish(T.source_event("remote"), RobotEvent(
            robot_id=ROBOT, kind="challenge", seq=req.seq, detail=body.model_dump_json()
        ).model_dump_json())

    server = asyncio.create_task(fake_gateway())
    with pytest.raises(ConfirmRefused):
        await client.request_confirm("estop_release", timeout_s=2.0)
    await server
    pump.cancel()
    await asyncio.gather(pump, return_exceptions=True)


def test_dashboard_release_without_gateway_keeps_the_direct_path():
    class Robot_:
        via_gateway = False
        released = 0

        def estop_release(self):
            self.released += 1

    robot = Robot_()
    handle(Supervisor(EventBus()), robot, {"cmd": "estop_release"}, confirm=None)
    assert robot.released == 1


async def test_dashboard_release_through_the_gateway_uses_the_flow():
    started = []

    class Flow:
        def start(self, action, posture=None):
            started.append(action)

        def resolve(self, trace, approved):
            started.append((trace, approved))
            return True

    class Robot_:
        via_gateway = True

        def estop_release(self):
            raise AssertionError("must not release directly")

    sup = Supervisor(EventBus())
    handle(sup, Robot_(), {"cmd": "estop_release"}, confirm=Flow())
    handle(sup, Robot_(), {"cmd": "confirm", "id": "x", "approved": True}, confirm=Flow())
    assert started == ["estop_release", ("x", True)]


# ---------------------------------------------------------------- workers
async def worker_rig(chat_handler=None, **kw):
    hub = InMemoryHub()
    link = hub.endpoint([])
    voice = hub.endpoint([T.rpc_reply("ask", "voice"), T.rpc_reply("stt", "voice")])
    await link.start()
    await voice.start()

    def handler(request):
        return chat_handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x/v1")
    return link, voice, ChatClient("liquid", "http://x/v1", "m", http=http)


def chat_ok(text):
    return lambda request: httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


async def reply_of(voice, model):
    msg = await asyncio.wait_for(anext(voice.messages()), 2)
    return model.model_validate_json(msg.payload)


class Vision:
    async def ask(self, jpeg, question):
        return f"seen {len(jpeg)} bytes"


class Snap:
    async def snapshot(self):
        return b"\xff\xd8xx"


async def test_ask_answers_text_questions():
    link, voice, chat = await worker_rig(chat_ok("بسبب الضوء"))
    svc = AskService(link, settings(), Snap(), Vision(), [chat])
    svc.on_request("t", AskRequest(trace="a1", text="ليش").model_dump_json().encode())
    reply = await reply_of(voice, AskReply)
    assert reply.ok and reply.text == "بسبب الضوء" and reply.provider == "liquid"


async def test_ask_with_image_uses_vision():
    link, voice, chat = await worker_rig(chat_ok("unused"))
    svc = AskService(link, settings(), Snap(), Vision(), [chat])
    request = AskRequest(trace="a2", text="شو هذا", need_image=True)
    svc.on_request("t", request.model_dump_json().encode())
    reply = await reply_of(voice, AskReply)
    assert reply.provider == "vision" and reply.text == "seen 4 bytes"


class FakePerception:
    def __init__(self, who="هاد سامي", facts="Fast detectors (they can be wrong) found: سامي"):
        self.who_text, self.facts_text = who, facts

    async def run(self, fn, *args):
        return fn(*args)

    def who(self, _frame):
        return self.who_text

    def facts(self, _frame):
        return self.facts_text


class PrefixVision:
    def __init__(self):
        self.calls = []

    async def ask(self, jpeg, question, local_prefix=""):
        self.calls.append((question, local_prefix))
        return "في كرسي قدامي"


def jpeg_bytes():
    import cv2
    import numpy as np

    ok, frame = cv2.imencode(".jpg", np.zeros((16, 16, 3), np.uint8))
    assert ok
    return frame.tobytes()


class SnapJpeg:
    async def snapshot(self):
        return jpeg_bytes()


async def test_facts_go_only_to_the_local_vision():
    link, voice, chat = await worker_rig()
    vision = PrefixVision()
    svc = AskService(link, settings(), SnapJpeg(), vision, [chat],
                     perception=FakePerception())
    svc.on_request("t", AskRequest(trace="p1", text="شو قدامك", need_image=True)
                   .model_dump_json().encode())
    reply = await reply_of(voice, AskReply)
    assert reply.ok and reply.text == "في كرسي قدامي" and reply.provider == "vision"
    assert vision.calls == [("شو قدامك", "Fast detectors (they can be wrong) found: سامي")]


async def test_who_question_is_answered_by_the_face_book():
    link, voice, chat = await worker_rig()
    vision = PrefixVision()
    svc = AskService(link, settings(), SnapJpeg(), vision, [chat],
                     perception=FakePerception())
    svc.on_request("t", AskRequest(trace="p2", text="مين هاد؟", need_image=True)
                   .model_dump_json().encode())
    reply = await reply_of(voice, AskReply)
    assert reply.ok and reply.text == "هاد سامي" and reply.provider == "faces"
    assert vision.calls == []


async def test_cloud_vision_backup_never_receives_names():
    class Down:
        async def ask(self, jpeg, question, local_prefix=""):
            raise httpx.TransportError("local vision down")

    class Backup:
        def __init__(self):
            self.questions = []

        async def ask(self, jpeg, question):
            self.questions.append(question)
            return "cloud answer"

    backup = Backup()
    answer = await RoutedVision(Down(), backup).ask(b"jpeg", "شو قدامك",
                                                    local_prefix="face: سامي")
    assert answer == "cloud answer" and backup.questions == ["شو قدامك"]


async def test_ask_falls_through_to_the_cloud_route():
    link, voice, bad = await worker_rig(lambda r: httpx.Response(500, json={}))
    _, _, good = await worker_rig(chat_ok("جواب"))
    good.name = "kimi"
    svc = AskService(link, settings(), Snap(), Vision(), [bad, good])
    svc.on_request("t", AskRequest(trace="a3", text="سؤال").model_dump_json().encode())
    assert (await reply_of(voice, AskReply)).provider == "kimi"


async def test_ask_reports_failure_when_every_route_is_down():
    link, voice, bad = await worker_rig(lambda r: httpx.Response(500, json={}))
    svc = AskService(link, settings(), Snap(), Vision(), [bad])
    svc.on_request("t", AskRequest(trace="a4", text="سؤال").model_dump_json().encode())
    reply = await reply_of(voice, AskReply)
    assert not reply.ok and reply.text == ""


async def test_ask_is_single_flight():
    gate = asyncio.Event()

    class Slow:
        name = "slow"

        async def ask(self, q):
            await gate.wait()
            return "done"

    link, voice, _ = await worker_rig(chat_ok("x"))
    svc = AskService(link, settings(), Snap(), Vision(), [Slow()])
    svc.on_request("t", AskRequest(trace="b1", text="a").model_dump_json().encode())
    svc.on_request("t", AskRequest(trace="b2", text="b").model_dump_json().encode())
    busy = await reply_of(voice, AskReply)
    assert (busy.trace, busy.ok, busy.error) == ("b2", False, "busy")
    gate.set()
    assert (await reply_of(voice, AskReply)).trace == "b1"


async def test_malformed_ask_is_dropped():
    link, voice, chat = await worker_rig(chat_ok("x"))
    svc = AskService(link, settings(), Snap(), Vision(), [chat])
    svc.on_request("t", b"{not json")
    assert voice.inbox.queue.empty() and not svc._busy


def test_chat_chain_from_config():
    s = settings(ask_route="liquid", ask_fallback="compat:moonshotai/kimi-k3",
                 compat_base_url="https://integrate.api.nvidia.com/v1", compat_api_key="k")
    chain = make_chat_chain(s)
    assert [c.name for c in chain] == ["liquid", "moonshotai/kimi-k3"]
    assert chain[1].http.headers["authorization"] == "Bearer k"


def test_compat_route_can_be_the_vision_fallback():
    s = settings(vision_fallback="compat:moonshotai/kimi-k3",
                 compat_base_url="https://x/v1", compat_api_key="k")
    assert isinstance(make_vision(s).backup, CompatVision)


class Engine:
    async def transcribe(self, pcm, language, prompt):
        return f"{len(pcm)}:{language}", 0.8


async def test_stt_worker_round_trip():
    link, voice, _ = await worker_rig(chat_ok("x"))
    worker = SttWorker(link, settings(), engine=Engine())
    audio = base64.b64encode(b"\x00\x00" * 8).decode()
    worker.on_request("t", SttRequest(trace="s1", audio_b64=audio).model_dump_json().encode())
    reply = await reply_of(voice, SttReply)
    assert reply.ok and reply.text == "16:ar" and reply.provider == "whisper-small"


async def test_stt_worker_reports_bad_audio():
    link, voice, _ = await worker_rig(chat_ok("x"))
    worker = SttWorker(link, settings(), engine=Engine())
    worker.on_request("t", SttRequest(trace="s2", audio_b64="@@@").model_dump_json().encode())
    assert not (await reply_of(voice, SttReply)).ok


# ---------------------------------------------------------------- observability
def test_trace_summary_and_file(tmp_path):
    store = TraceStore(tmp_path / "t.jsonl")
    for ms in (100.0, 200.0, 300.0):
        out = store.add(VoiceTurn(trace="c", route="grammar", stt_ms=ms)
                        .model_dump_json().encode())
    assert out["stages"]["stt"] == {"n": 3, "p50": 200.0, "p95": 300.0}
    assert out["paths"] == {"grammar": 3}
    assert len((tmp_path / "t.jsonl").read_text().splitlines()) == 3


def report(service="system", **kwargs):
    return HealthReport(robot_id=ROBOT, service=service, **kwargs)


@pytest.mark.parametrize("kwargs,word", [
    ({"metrics": {"temp_c": 82.0}}, "CPU"), ({"metrics": {"throttled_flags": 4.0}}, "throttled"),
    ({"metrics": {"mem_available_mb": 100.0}}, "memory"),
    ({"metrics": {"disk_free_mb": 10.0}}, "disk"),
    ({"info": {"failed_units": "ollama.service"}}, "failed"),
    ({"info": {"tailscale_path": "none"}}, "Tailscale"),
])
def test_health_conditions(kwargs, word):
    assert word in assess(report(**kwargs))[0]


def test_past_throttle_is_not_an_alert():
    assert assess(report(metrics={"throttled_flags": float(0x50000)})) == []


def test_repeated_speech_timeouts_are_an_alert():
    assert "timing out" in assess(report("voice", metrics={"stt_timeouts": 3.0}))[0]
    assert assess(report("voice", metrics={"stt_timeouts": 2.0})) == []


def test_a_dead_service_is_an_alert():
    assert "is down" in assess(report("voice", level="down", detail="lost"))[0]
    assert assess(report("voice", level="degraded", detail="starting")) == []


def test_health_alert_cooldown():
    now = [0.0]
    monitor = HealthMonitor(EventBus(), clock=lambda: now[0])
    payload = report(metrics={"temp_c": 85.0}).model_dump_json().encode()
    assert monitor.on_report(payload) and not monitor.on_report(payload)
    now[0] = 301.0
    assert monitor.on_report(payload)


# ---------------------------------------------------------------- telegram
class FakeFlow:
    def __init__(self, refuse=False):
        self.refuse, self.resolved = refuse, []

    def needs_wake(self, posture):
        return posture != "relax"

    async def begin(self, action, posture=None):
        if self.refuse:
            raise ConfirmRefused("no camera")
        from spider_brain.robot_client import Confirmation

        return Confirmation("chal", action, "ab", 30.0, b"\xff\xd8x")

    def resolve(self, trace, approved):
        self.resolved.append((trace, approved))
        return True


def telegram(flow):
    from types import SimpleNamespace

    from spider_brain.telegram import TelegramBot

    posts = []

    def handler(request):
        posts.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    class Robot_:
        via_gateway = True
        released = 0

        def estop_release(self):
            self.released += 1

        async def posture(self, posture, human=False):
            return f"direct {posture}"

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://t")
    svc = SimpleNamespace(robot=Robot_(), confirm=flow, supervisor=None)
    return TelegramBot(svc, "tok", {1}, http=http), posts, svc


async def test_telegram_release_sends_the_frame_with_buttons_and_does_not_release():
    bot, posts, svc = telegram(FakeFlow())
    await bot.command(1, "/release")
    assert svc.robot.released == 0
    assert "sendPhoto" in str(posts[-1].url) and b"cf:chal:1" in posts[-1].content


async def test_telegram_stand_from_limp_uses_the_flow():
    bot, posts, svc = telegram(FakeFlow())
    await bot.command(1, "/stand")
    assert "sendPhoto" in str(posts[-1].url)


async def test_telegram_refusal_is_reported():
    bot, posts, _ = telegram(FakeFlow(refuse=True))
    await bot.command(1, "/release")
    assert b"Refused" in posts[-1].content


async def test_telegram_confirm_button_resolves_and_ignores_strangers():
    flow = FakeFlow()
    bot, _, _ = telegram(flow)
    await bot._callback({"id": "q", "from": {"id": 2}, "data": "cf:chal:1"})
    assert flow.resolved == []
    await bot._callback({"id": "q", "from": {"id": 1}, "data": "cf:chal:1",
                         "message": {"chat": {"id": 1}}})
    assert flow.resolved == [("chal", True)]
