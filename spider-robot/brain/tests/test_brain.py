import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from spider_body.config import load_config
from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank
from spider_body.main import command_loop, control_loop, state_loop
from spider_body.robot import Robot
from spider_common.link import InMemoryHub
from spider_common.protocol import Topics
from starlette.websockets import WebSocketDisconnect

from spider_brain.calls import PlanStep, ToolCall, ToolOutcome
from spider_brain.config import Settings
from spider_brain.planner import ClaudePlanner, LiquidPlanner
from spider_brain.policy import Risk, classify, needs_approval
from spider_brain.robot_client import RobotClient
from spider_brain.runner import run_task
from spider_brain.supervision.events import EventBus
from spider_brain.supervision.server import create_app
from spider_brain.supervision.supervisor import Supervisor
from spider_brain.tools import TOOL_SPECS, anthropic_tools

SIM_CFG = Path(__file__).resolve().parents[2] / "body" / "config" / "robot.sim.yaml"


def settings(**kw) -> Settings:
    base = dict(autonomy="autonomous", dashboard=False, online_timeout_s=5,
                walk_speed_slow=0.08, walk_speed_normal=0.1, turn_speed_dps=60)
    base.update(kw)
    return Settings(_env_file=None, **base)


# ----------------------------------------------------------------------------- policy
@pytest.mark.parametrize(
    "name,args,risk",
    [
        ("scan_surroundings", {}, Risk.LOW),
        ("walk", {"direction": "forward", "distance_m": 0.3, "speed": "slow"}, Risk.MEDIUM),
        ("walk", {"direction": "forward", "distance_m": 1.2, "speed": "slow"}, Risk.HIGH),
        ("walk", {"distance_m": "lots"}, Risk.HIGH),
        ("set_posture", {"posture": "relax"}, Risk.HIGH),
        ("self_destruct", {}, Risk.HIGH),
    ],
)
def test_classify(name, args, risk):
    assert classify(ToolCall("1", name, args), settings()) == risk


def test_approval_thresholds():
    assert needs_approval(Risk.MEDIUM, "guarded")
    assert not needs_approval(Risk.MEDIUM, "autonomous")
    assert needs_approval(Risk.LOW, "supervised")


def test_tool_schemas_are_strict_compatible():
    for name, _, schema in TOOL_SPECS:
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"]), name
        assert "minimum" not in json.dumps(schema)
    assert all(t["strict"] for t in anthropic_tools())


# ----------------------------------------------------------------------------- planners
class _Block:
    def __init__(self, **kw):
        self.kw = kw

    def model_dump(self, exclude_none=True):
        return dict(self.kw)


class FakeAnthropic:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


async def test_claude_planner_roundtrip():
    resp1 = SimpleNamespace(stop_reason="tool_use", content=[
        _Block(type="thinking", thinking="check first", signature="sig"),
        _Block(type="tool_use", id="tu1", name="get_status", input={}),
    ])
    resp2 = SimpleNamespace(stop_reason="end_turn", content=[_Block(type="text", text="All done.")])
    fake = FakeAnthropic([resp1, resp2])
    p = ClaudePlanner(settings(), client=fake)
    p.start("check the robot")
    step = await p.next_step()
    assert [c.name for c in step.calls] == ["get_status"] and step.thinking == "check first"
    p.add_results([(step.calls[0], ToolOutcome("Mode: standing"))])
    step2 = await p.next_step()
    assert step2.done and step2.text == "All done."
    req = fake.calls[1]
    assert req["fallbacks"] == "default" and req["output_config"] == {"effort": "medium"}
    assert req["thinking"]["type"] == "adaptive"
    assert req["cache_control"] == {"type": "ephemeral"}  # whole conversation is cached
    # history is append-only: thinking block passed back unchanged, results in one user turn
    assert req["messages"][1]["content"][0] == {"type": "thinking", "thinking": "check first",
                                                "signature": "sig"}
    assert req["messages"][2]["content"][0]["tool_use_id"] == "tu1"


async def test_claude_refusal_ends_task():
    fake = FakeAnthropic([SimpleNamespace(stop_reason="refusal", content=[])])
    p = ClaudePlanner(settings(), client=fake)
    p.start("x")
    assert (await p.next_step()).done


async def test_liquid_planner_parses_tool_calls():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            call = {"type": "function", "function": {
                "name": "walk",
                "arguments": '{"direction":"forward","distance_m":0.3,"speed":"slow"}'}}
            msg = {"content": "", "tool_calls": [call]}
            return httpx.Response(
                200, json={"choices": [{"finish_reason": "tool_calls", "message": msg}]}
            )
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                                      "message": {"content": "done"}}]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x/v1")
    p = LiquidPlanner(settings(planner="liquid"), http=http)
    p.start("go")
    step = await p.next_step()
    assert step.calls[0].name == "walk" and step.calls[0].args["distance_m"] == 0.3
    p.add_results([(step.calls[0], ToolOutcome("Walked about 0.30 m forward."))])
    assert (await p.next_step()).text == "done"
    assert seen[1]["messages"][-1]["role"] == "tool"
    assert seen[0]["tools"][0]["type"] == "function"


# ----------------------------------------------------------------------------- dashboard
def test_dashboard_rejects_bad_origin_and_token():
    bus = EventBus()
    sup = Supervisor(bus)
    robot = RobotClient(InMemoryHub().endpoint([]), "r1", bus)
    client = TestClient(create_app(sup, robot, run_token="secret", port=8765))
    assert client.get("/").status_code == 200
    with client.websocket_connect("/ws", headers={"origin": "http://evil.example"}) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4403
    with client.websocket_connect("/ws", headers={"origin": "http://127.0.0.1:8765"}) as ws:
        ws.send_json({"token": "wrong"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


# ----------------------------------------------------------------------------- end to end
class ScriptedPlanner:
    def __init__(self, script, world=None):
        self.script = list(script)
        self.results: list[tuple[ToolCall, ToolOutcome]] = []
        self.world = world
        self.x_after: list[float] = []

    def start(self, task):
        pass

    async def next_step(self):
        if not self.script:
            return PlanStep(text="Finished the script.")
        name, args = self.script.pop(0)
        return PlanStep(text="", calls=[ToolCall(f"c{len(self.script)}", name, args)])

    def add_results(self, results):
        self.results.extend(results)
        if self.world is not None:
            self.x_after.append(self.world.x)


def world_x_after_walk(planner):
    return planner.x_after[4]


class FakeVision:
    async def ask(self, jpeg, question):
        assert jpeg[:2] == b"\xff\xd8"
        return "An orange box in the centre, about 1 m away."


async def _sim_body(hub, obstacles):
    cfg = load_config(SIM_CFG, calibration="/nonexistent")
    cfg.state_hz = 20
    cfg.gait.posture_speed_mps = 0.2
    world = SimWorld(obstacles=obstacles)
    t = Topics(cfg.robot_id)
    link = hub.endpoint([t.cmd])
    robot = Robot(cfg, FakeServoBank(), SimLidar(cfg.lidar, world), FakeCamera(cfg.camera), link)
    lidar = robot.lidar
    await link.start()
    loops = (control_loop(robot, world), command_loop(robot, link), state_loop(robot, link),
             lidar.run())
    tasks = [asyncio.create_task(c) for c in loops]
    return robot, world, tasks


async def test_end_to_end_walk_look_and_obstacle_stop():
    hub = InMemoryHub()
    body, world, tasks = await _sim_body(hub, obstacles=[(0.9, 0.0, 0.1)])
    brain_link = hub.endpoint(RobotClient.subscriptions("spider-01"))
    planner = ScriptedPlanner(world=world, script=[
        ("get_status", {}),
        ("set_posture", {"posture": "stand"}),
        ("look", {"question": "what is ahead?"}),
        ("walk", {"direction": "forward", "distance_m": 0.2, "speed": "normal"}),
        ("walk", {"direction": "forward", "distance_m": 1.0, "speed": "normal"}),
        ("scan_surroundings", {}),
        ("turn", {"angle_deg": 90}),  # too close to the obstacle to turn: refused
        ("walk", {"direction": "backward", "distance_m": 0.3, "speed": "normal"}),
        ("turn", {"angle_deg": 90}),
    ])
    try:
        summary = await asyncio.wait_for(
            run_task("test", settings(approval_free_walk_m=2.0), link=brain_link,
                     planner=planner, vision=FakeVision()),
            90,
        )
    finally:
        for t in tasks:
            t.cancel()
    texts = {c.name + str(i): o.text for i, (c, o) in enumerate(planner.results)}
    outs = [o for _, o in planner.results]
    assert summary == "Finished the script."
    assert "standing" in outs[1].text
    assert "orange box" in outs[2].text
    assert outs[3].text.startswith("Walked about 0.")
    assert "obstacle_stop" in outs[4].text, texts  # second walk is stopped by the obstacle
    # obstacle surface at 0.8 m, legs reach 0.24 m: stop ~0.15 m before the legs touch
    assert 0.08 < 0.8 - world_x_after_walk(planner) - 0.24 <= 0.16
    assert "front" in outs[5].text
    assert "too close to turn" in outs[6].text
    assert outs[7].text.startswith("Walked about 0.")
    assert "Turned about" in outs[8].text and world.yaw > 1.0
    assert body.mode == "standing"


async def test_high_risk_without_dashboard_is_rejected_not_hung():
    hub = InMemoryHub()
    body, world, tasks = await _sim_body(hub, obstacles=[])
    brain_link = hub.endpoint(RobotClient.subscriptions("spider-01"))
    planner = ScriptedPlanner([("set_posture", {"posture": "relax"})])
    try:
        await asyncio.wait_for(
            run_task("t", settings(), link=brain_link, planner=planner, vision=FakeVision()), 20)
    finally:
        for t in tasks:
            t.cancel()
    call, out = planner.results[0]
    assert out.is_error and "no dashboard" in out.text


async def _client_with_body(obstacles=None):
    hub = InMemoryHub()
    body, world, tasks = await _sim_body(hub, obstacles=obstacles or [])
    link = hub.endpoint(RobotClient.subscriptions("spider-01"))
    robot = RobotClient(link, "spider-01")
    await link.start()
    tasks += [asyncio.create_task(robot.run()), asyncio.create_task(robot.heartbeat_loop(5))]
    assert await robot.wait_online(5)
    assert "standing" in await robot.posture("stand")
    return body, world, robot, tasks


async def test_dashboard_stop_cancels_running_walk():
    # Reviewer finding: Stop/Pause did not stop a walk; the tool kept renewing Moves.
    from spider_brain.supervision.server import handle

    body, world, robot, tasks = await _client_with_body()
    try:
        walk = asyncio.create_task(robot.walk("forward", 1.0, 0.1, "tripod"))
        await asyncio.sleep(1.5)
        handle(Supervisor(EventBus()), robot, {"cmd": "robot_stop"})
        result = await asyncio.wait_for(walk, 5)
        x_stop = world.x
        await asyncio.sleep(1.5)
        assert result.stopped_by == "cancelled by the owner"
        assert world.x - x_stop < 0.03  # really stopped (only the deceleration ramp)
    finally:
        for t in tasks:
            t.cancel()


async def test_network_partition_is_not_reported_as_success():
    # Reviewer finding: the walk tool kept integrating the last cached velocity.
    body, world, robot, tasks = await _client_with_body()
    state_task = tasks[2]  # body state_loop
    try:
        walk = asyncio.create_task(robot.walk("forward", 0.5, 0.1, "tripod"))
        await asyncio.sleep(1.0)
        state_task.cancel()  # telemetry stops arriving
        result = await asyncio.wait_for(walk, 10)
        assert not result.completed
        assert "telemetry lost" in result.stopped_by
    finally:
        for t in tasks:
            t.cancel()


class TwoCallPlanner(ScriptedPlanner):
    async def next_step(self):
        if self.script:
            self.script = []
            return PlanStep(text="", calls=[ToolCall("a", "scan_surroundings", {}),
                                            ToolCall("b", "get_status", {})])
        return PlanStep(text="done")


async def test_read_only_calls_run_in_parallel():
    hub = InMemoryHub()
    body, world, tasks = await _sim_body(hub, obstacles=[])
    planner = TwoCallPlanner(script=[1])
    try:
        await asyncio.wait_for(run_task("t", settings(), link=hub.endpoint(
            RobotClient.subscriptions("spider-01")), planner=planner, vision=FakeVision()), 20)
    finally:
        for t in tasks:
            t.cancel()
    assert [c.name for c, _ in planner.results] == ["scan_surroundings", "get_status"]
    assert all(not o.is_error for _, o in planner.results)


async def test_claude_task_budget_stops_the_task():
    usage = SimpleNamespace(input_tokens=200_000, output_tokens=10_000,
                            cache_read_input_tokens=0, cache_creation_input_tokens=0)
    resp = SimpleNamespace(stop_reason="tool_use", usage=usage, content=[
        _Block(type="tool_use", id="t1", name="get_status", input={})])
    p = ClaudePlanner(settings(max_task_usd=0.5), client=FakeAnthropic([resp]))
    p.start("x")
    await p.next_step()  # 200k*$4/M + 10k*$20/M = $1.00
    p.add_results([(ToolCall("t1", "get_status", {}), ToolOutcome("ok"))])
    step = await p.next_step()
    assert step.done and "budget" in step.text
