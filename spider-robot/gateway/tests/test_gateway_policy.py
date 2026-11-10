"""Behaviour added by the hardening milestone: each test names the defect or decision it covers."""

import hashlib
import json

import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import (
    ConfirmChallenge,
    ConfirmRequest,
    EStopRelease,
    Heartbeat,
    Move,
    Posture,
    RobotEvent,
    RobotState,
    Snapshot,
    Stop,
    Topics,
)

from spider_gateway.gateway import Gateway, GatewayConfig, SourceClock
from spider_gateway.policy import DEFAULT_POLICIES, load_policies

ROBOT = "spider-01"
T = Topics(ROBOT)
JPEG = b"\xff\xd8frame\xff\xd9"


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
async def rig():
    link = InMemoryHub().endpoint([])
    await link.start()
    clock = Clock()
    gw = Gateway(link, ROBOT, clock=clock, wall=lambda: 1000.0 + clock.now)
    return gw, link, clock


def sent(link):
    return [json.loads(m.payload) for m in link.published if m.topic == T.cmd]


def replies(link, source):
    return [json.loads(m.payload) for m in link.published if m.topic == T.source_event(source)]


def move(clock, seq=1, session="s", **kw):
    fields = {"vx": 0.05, "duration_s": 1.0, **kw}
    return Move(seq=seq, session=session, ts=1000.0 + clock.now, **fields).model_dump_json()


def stop(clock, seq=1, session="v"):
    return Stop(seq=seq, session=session, ts=1000.0 + clock.now).model_dump_json()


async def test_voice_stop_is_not_undone_by_the_next_planner_renewal(rig):
    gw, link, clock = rig
    gw.on_request("planner", move(clock, seq=1, session="p"))
    clock.now += 0.2
    gw.on_request("voice", stop(clock))
    clock.now += 0.3  # the planner renews every 0.5 s and has not heard about the Stop
    gw.on_request("planner", move(clock, seq=2, session="p"))
    assert [c["type"] for c in sent(link)] == ["move", "stop"]
    assert replies(link, "planner")[-1]["kind"] == "rejected"


async def test_displaced_owner_is_told_at_once(rig):
    gw, link, clock = rig
    gw.on_request("remote", move(clock, session="r"))
    gw.on_request("voice", stop(clock))
    assert replies(link, "remote")[-1]["kind"] == "preempted"


async def test_motion_resumes_after_the_holdoff(rig):
    gw, link, clock = rig
    gw.on_request("voice", stop(clock))
    clock.now += gw.config.stop_holdoff_s + 0.01
    gw.on_request("planner", move(clock, session="p"))
    assert sent(link)[-1]["type"] == "move"


async def test_stop_does_not_hold_off_higher_priority_sources(rig):
    gw, link, clock = rig
    gw.on_request("planner", stop(clock, session="p"))
    gw.on_request("voice", move(clock, session="v"))
    assert sent(link)[-1]["type"] == "move"


async def test_voice_takeover_tells_the_old_owner(rig):
    gw, link, clock = rig
    gw.on_request("planner", move(clock, session="p", duration_s=1.5))
    gw.on_request("voice", move(clock, session="v"))
    assert replies(link, "planner")[-1]["kind"] == "preempted"


@pytest.mark.parametrize("source,speed,turn,secs", [
    ("voice", 0.08, 0.5, 2.0), ("remote", 0.05, 0.3, 1.0), ("planner", 0.06, 0.45, 1.0)])
async def test_each_source_is_capped(rig, source, speed, turn, secs):
    gw, link, clock = rig
    gw.on_request(source, move(clock, vx=0.3, vy=0.4, wz=2.0, duration_s=10.0))
    out = sent(link)[-1]
    assert out["vx"] ** 2 + out["vy"] ** 2 == pytest.approx(speed ** 2)
    assert out["wz"] == pytest.approx(turn) and out["duration_s"] == pytest.approx(secs)


async def test_remote_cap_is_tighter_than_voice(rig):
    gw, *_ = rig
    assert gw.policies["remote"].max_speed_mps < gw.policies["voice"].max_speed_mps
    assert gw.policies["remote"].max_duration_s < gw.policies["voice"].max_duration_s


async def test_forwarded_commands_carry_the_pi_clock(rig):
    gw, link, clock = rig
    payload = Move(seq=1, session="r", ts=5.0, vx=0.05, duration_s=1.0).model_dump_json()
    gw.on_request("remote", payload)  # the sender clock is 1095 s behind
    assert sent(link)[-1]["ts"] == pytest.approx(1000.0 + clock.now)


async def test_invalid_payloads_do_not_count_as_life(rig):
    gw, link, clock = rig
    gw.on_request("remote", move(clock, duration_s=1.5, session="r"))
    clock.now += 1.0
    gw.on_request("remote", b"not json")
    clock.now += 0.7
    gw.tick()
    assert "stop" in [c["type"] for c in sent(link)]


def test_source_clock_ignores_a_constant_clock_offset():
    clock = SourceClock()
    clock.observe(0.0, 500.0, 0.5)
    clock.observe(0.5, 500.01, 0.5)
    assert clock.observe(1.0, 500.02, 0.5) == pytest.approx(0.02)


def test_source_clock_sees_queueing():
    clock = SourceClock()
    clock.observe(0.0, 1.0, 0.5)
    assert clock.observe(1.0, 1.9, 0.5) == pytest.approx(0.9)


def test_source_clock_rebaselines_after_a_settled_step():
    clock = SourceClock()
    clock.observe(0.0, 0.0, 0.5)
    for t in range(1, 5):  # every message 5 s late, all agreeing: a clock step, not a backlog
        clock.observe(float(t), 5.0, 0.5)
    assert clock.rebaselines == 1 and clock.excess == 0.0


def test_source_clock_keeps_refusing_a_draining_backlog():
    clock = SourceClock()
    clock.observe(0.0, 0.0, 0.5)
    for t, delay in enumerate((9.0, 7.0, 5.0, 3.0, 1.5)):
        clock.observe(1.0 + t, delay, 0.5)
    assert clock.rebaselines == 0 and clock.excess > 0.5


async def test_late_heartbeat_does_not_keep_a_source_alive(rig):
    gw, link, clock = rig
    gw.on_request("remote", move(clock, session="r"))
    clock.now += 0.7
    gw.on_request("remote", Heartbeat(ts=1000.0 + clock.now - 3.0).model_dump_json())
    clock.now += 0.9  # 1.6 s since the last on-time message
    gw.tick()
    assert sent(link)[-1]["type"] == "stop"


async def test_late_posture_is_refused(rig):
    gw, link, clock = rig
    gw.on_state(state("standing"))
    gw.on_request("voice", Heartbeat(ts=1000.0 + clock.now).model_dump_json())
    gw.on_request("voice", Posture(seq=1, session="v", ts=1000.0 + clock.now - 3.0,
                                   posture="sit").model_dump_json())
    assert sent(link) == [] and "late" in replies(link, "voice")[-1]["detail"]


async def test_v2_source_is_accepted_and_reissued_as_v3(rig):
    gw, link, clock = rig
    gw.on_request("planner", Move(v=2, seq=1, session="p", ts=1000.0 + clock.now, vx=0.05,
                                  duration_s=0.5).model_dump_json())
    assert sent(link)[-1]["v"] == 3


async def test_unsupported_protocol_is_refused_and_is_not_a_sign_of_life(rig):
    gw, link, clock = rig
    gw.on_request("planner", Heartbeat(v=1, ts=1000.0 + clock.now).model_dump_json())
    assert "not supported" in replies(link, "planner")[-1]["detail"]
    assert not gw._alive("planner", clock.now)


async def test_clamped_notice_is_rate_limited(rig):
    gw, link, clock = rig
    gw.on_request("remote", move(clock, seq=1, session="r", vx=0.3))
    gw.on_request("remote", move(clock, seq=2, session="r", vx=0.3))
    assert sum(r["kind"] == "clamped" for r in replies(link, "remote")) == 1


async def test_snapshot_rate_limit(rig):
    gw, link, clock = rig
    for seq, rid in ((1, "a"), (2, "b")):
        gw.on_request("planner", Snapshot(seq=seq, session="p", ts=1000.0 + clock.now,
                                          request_id=rid).model_dump_json())
    assert [c["request_id"] for c in sent(link)] == ["a"]
    assert replies(link, "planner")[-1]["detail"] == "snapshot rate limit"


async def test_replies_carry_the_trace_of_the_command(rig):
    gw, link, clock = rig
    gw.on_request("voice", stop(clock))
    gw.on_request("planner", Move(seq=1, session="p", ts=1000.0 + clock.now, vx=0.05, trace="tr1",
                                  duration_s=0.5).model_dump_json())
    assert replies(link, "planner")[-1]["trace"] == "tr1"


# ---------------------------------------------------------------- attacks from the design review
async def test_planner_stop_does_not_block_voice(rig):
    gw, link, clock = rig
    gw.on_request("planner", stop(clock, session="p"))
    gw.on_request("voice", move(clock, session="v"))
    assert [c["type"] for c in sent(link)] == ["stop", "move"]


async def test_a_planner_stop_cannot_undo_a_voice_stop(rig):
    gw, link, clock = rig
    gw.on_request("voice", stop(clock))
    gw.on_request("planner", stop(clock, seq=1, session="p"))
    clock.now += 0.2
    gw.on_request("planner", move(clock, seq=2, session="p"))
    assert [c["type"] for c in sent(link)] == ["stop", "stop"]


async def test_planner_move_soon_after_a_voice_stop_is_refused_and_told(rig):
    gw, link, clock = rig
    gw.on_request("voice", stop(clock))
    clock.now += 0.76
    gw.on_request("planner", move(clock, seq=2, session="p"))
    assert [c["type"] for c in sent(link)] == ["stop"]
    assert "held off" in replies(link, "planner")[-1]["detail"]


async def test_one_frame_cannot_release_two_estops(rig):
    gw, link, clock = rig
    ch = challenge_for(gw, link, clock)
    gw.on_request("remote", release(clock, ch))
    clock.now += 11.0
    gw.on_request("remote", release(clock, ch))
    assert sum(c["type"] == "estop_release" for c in sent(link)) == 1


# ---------------------------------------------------------------- the bench source
@pytest.fixture
async def bench_rig():
    link = InMemoryHub().endpoint([])
    await link.start()
    clock = Clock()
    gw = Gateway(link, ROBOT, clock=clock, wall=lambda: 1000.0 + clock.now,
                 config=GatewayConfig(bench_enabled=True))
    return gw, link, clock


async def test_bench_is_ignored_unless_enabled(rig):
    gw, link, clock = rig
    gw.on_request("bench", move(clock, session="b"))
    gw.on_request("bench", Posture(seq=2, session="b", ts=1000.0 + clock.now,
                                   posture="stand").model_dump_json())
    assert sent(link) == []


async def test_bench_is_capped_at_the_body_speed(bench_rig):
    gw, link, clock = bench_rig
    gw.on_request("bench", move(clock, session="b", vx=0.4, duration_s=9.0))
    out = sent(link)[-1]
    assert out["vx"] == pytest.approx(0.12) and out["duration_s"] == 3.0


async def test_bench_may_wake_a_limp_robot(bench_rig):
    gw, link, clock = bench_rig
    gw.on_state(state("relaxed"))
    gw.on_request("bench", Posture(seq=1, session="b", ts=1000.0 + clock.now,
                                   posture="stand").model_dump_json())
    assert sent(link)[-1]["type"] == "posture"


async def test_a_voice_stop_holds_the_bench_off(bench_rig):
    gw, link, clock = bench_rig
    gw.on_request("voice", stop(clock))
    clock.now += 0.2
    gw.on_request("bench", move(clock, seq=2, session="b"))
    assert [c["type"] for c in sent(link)] == ["stop"]


async def test_bench_may_not_release_an_estop(bench_rig):
    gw, link, clock = bench_rig
    gw.on_request("bench", EStopRelease(seq=1, session="b",
                                        ts=1000.0 + clock.now).model_dump_json())
    assert sent(link) == []


# ---------------------------------------------------------------- the physical release button
def button_release(clock, age=0.0):
    return EStopRelease(seq=1, session="b", ts=1000.0 + clock.now - age).model_dump_json()


async def test_button_release_needs_no_network_or_frame(rig):
    gw, link, clock = rig
    gw.on_request("button", button_release(clock))
    assert sent(link)[-1]["type"] == "estop_release"


@pytest.mark.parametrize("cmd", [
    Move(seq=1, session="b", vx=0.05, duration_s=0.5),
    Posture(seq=1, session="b", posture="stand"),
    Stop(seq=1, session="b"),
    Heartbeat(seq=1, session="b"),
    Snapshot(seq=1, session="b", request_id="a"),
])
async def test_button_source_can_do_nothing_else(rig, cmd):
    gw, link, clock = rig
    gw.on_request("button", cmd.model_copy(update={"ts": 1000.0 + clock.now}).model_dump_json())
    assert sent(link) == []
    assert replies(link, "button")[-1]["kind"] == "rejected"


async def test_button_is_refused_while_a_source_owns_the_robot(rig):
    gw, link, clock = rig
    gw.on_request("voice", move(clock, session="v"))
    count = len(sent(link))
    gw.on_request("button", button_release(clock))
    assert len(sent(link)) == count and "in control" in replies(link, "button")[-1]["detail"]


async def test_button_does_not_keep_the_robot_alive(rig):
    gw, link, clock = rig
    gw.on_request("button", button_release(clock))
    gw.tick()
    assert not any(c["type"] == "heartbeat" for c in sent(link))


async def test_stale_button_press_is_refused(rig):
    gw, link, clock = rig
    gw.on_request("button", button_release(clock, age=5.0))
    assert sent(link) == []


def test_default_policies_keep_release_to_remote_only():
    assert [n for n, p in DEFAULT_POLICIES.items() if p.may_release_estop] == ["remote"]
    assert DEFAULT_POLICIES["remote"].needs_frame_proof


def test_policy_file_may_tighten_but_not_invert(tmp_path):
    fine = tmp_path / "ok.yaml"
    fine.write_text("remote:\n  max_speed_mps: 0.03\n")
    assert load_policies(fine)["remote"].max_speed_mps == 0.03
    bad = tmp_path / "bad.yaml"
    bad.write_text("remote:\n  max_speed_mps: 0.2\n")
    with pytest.raises(ValueError):
        load_policies(bad)


async def test_move_stuck_in_a_network_queue_is_refused(rig):
    gw, link, clock = rig
    for _ in range(6):
        gw.on_request("remote", Heartbeat(ts=1000.0 + clock.now - 0.02).model_dump_json())
        clock.now += 0.5
    late = Move(seq=9, session="r", ts=1000.0 + clock.now - 1.2, vx=0.05, duration_s=1.0)
    gw.on_request("remote", late.model_dump_json())
    assert sent(link) == []
    assert "late" in replies(link, "remote")[-1]["detail"]


async def test_stop_is_never_refused_for_being_late(rig):
    gw, link, clock = rig
    for _ in range(6):
        gw.on_request("remote", Heartbeat(ts=1000.0 + clock.now).model_dump_json())
        clock.now += 0.5
    old = Stop(seq=3, session="r", ts=1000.0 + clock.now - 9.0)
    gw.on_request("remote", old.model_dump_json())
    assert sent(link)[-1]["type"] == "stop"


# ---------------------------------------------------------------- confirmed actions
def challenge_for(gw, link, clock, action="estop_release", rid="req1"):
    gw.on_request("remote", ConfirmRequest(
        seq=4, session="r", ts=1000.0 + clock.now, action=action, request_id=rid
    ).model_dump_json())
    assert sent(link)[-1]["type"] == "snapshot" and sent(link)[-1]["request_id"] == rid
    gw.on_camera(rid, JPEG)
    event = replies(link, "remote")[-1]
    assert event["kind"] == "challenge" and event["seq"] == 4
    return ConfirmChallenge.model_validate_json(event["detail"])


def release(clock, ch, sha=None):
    return EStopRelease(seq=5, session="r", ts=1000.0 + clock.now, challenge=ch.id,
                        frame_sha256=sha if sha is not None else ch.sha256).model_dump_json()


async def test_remote_release_needs_the_frame_it_was_shown(rig):
    gw, link, clock = rig
    ch = challenge_for(gw, link, clock)
    assert ch.sha256 == hashlib.sha256(JPEG).hexdigest()
    gw.on_request("remote", release(clock, ch))
    assert sent(link)[-1]["type"] == "estop_release"


async def test_challenge_is_single_use(rig):
    gw, link, clock = rig
    ch = challenge_for(gw, link, clock)
    gw.on_request("remote", release(clock, ch))
    count = len(sent(link))
    gw.on_request("remote", release(clock, ch))
    assert len(sent(link)) == count
    assert replies(link, "remote")[-1]["kind"] == "rejected"


async def test_challenge_expires(rig):
    gw, link, clock = rig
    ch = challenge_for(gw, link, clock)
    clock.now += gw.config.challenge_ttl_s + 0.1
    gw.on_request("remote", release(clock, ch))
    assert sent(link)[-1]["type"] == "snapshot"


async def test_wrong_frame_hash_is_refused(rig):
    gw, link, clock = rig
    ch = challenge_for(gw, link, clock)
    gw.on_request("remote", release(clock, ch, sha="0" * 64))
    assert sent(link)[-1]["type"] == "snapshot"


async def test_challenge_is_bound_to_its_action(rig):
    gw, link, clock = rig
    ch = challenge_for(gw, link, clock, action="wake_from_limp")
    gw.on_request("remote", release(clock, ch))
    assert sent(link)[-1]["type"] == "snapshot"


@pytest.mark.parametrize("source", ["voice", "planner"])
async def test_only_remote_can_ask_for_a_confirmation(rig, source):
    gw, link, clock = rig
    gw.on_request(source, ConfirmRequest(
        seq=1, session="x", ts=1000.0 + clock.now, action="estop_release", request_id="r"
    ).model_dump_json())
    assert sent(link) == [] and replies(link, source)[-1]["kind"] == "rejected"


async def test_snapshot_failure_reaches_the_requester(rig):
    gw, link, clock = rig
    gw.on_request("remote", ConfirmRequest(
        seq=4, session="r", ts=1000.0 + clock.now, action="estop_release", request_id="rq"
    ).model_dump_json())
    gw.on_event(RobotEvent(robot_id=ROBOT, kind="snapshot_failed", seq=1,
                           detail="rq: camera gone").model_dump_json())
    assert replies(link, "remote")[-1]["kind"] == "rejected"
    assert gw._pending == {}


async def test_camera_frames_for_others_are_ignored(rig):
    gw, link, _ = rig
    gw.on_camera("someone-else", JPEG)
    assert link.published == []


def state(mode):
    return RobotState(robot_id=ROBOT, mode=mode).model_dump_json()


@pytest.mark.parametrize("mode", ["relaxed", "fallen"])
async def test_remote_cannot_wake_a_limp_robot_without_a_frame(rig, mode):
    gw, link, clock = rig
    gw.on_state(state(mode))
    gw.on_request("remote", Posture(seq=1, session="r", ts=1000.0 + clock.now,
                                    posture="stand").model_dump_json())
    assert sent(link) == [] and "frame" in replies(link, "remote")[-1]["detail"]


async def test_remote_wake_works_with_a_confirmed_frame(rig):
    gw, link, clock = rig
    gw.on_state(state("relaxed"))
    ch = challenge_for(gw, link, clock, action="wake_from_limp")
    gw.on_request("remote", Posture(seq=6, session="r", ts=1000.0 + clock.now, posture="stand",
                                    challenge=ch.id, frame_sha256=ch.sha256).model_dump_json())
    assert sent(link)[-1]["type"] == "posture"


async def test_planner_can_never_wake_a_limp_robot(rig):
    gw, link, clock = rig
    gw.on_state(state("fallen"))
    gw.on_request("planner", Posture(seq=1, session="p", ts=1000.0 + clock.now,
                                     posture="stand").model_dump_json())
    assert sent(link) == []


async def test_unknown_mode_counts_as_limp(rig):
    gw, link, clock = rig
    gw.on_request("remote", Posture(seq=1, session="r", ts=1000.0 + clock.now,
                                    posture="sit").model_dump_json())
    assert sent(link) == []


async def test_voice_may_wake_because_someone_is_there(rig):
    gw, link, clock = rig
    gw.on_state(state("relaxed"))
    gw.on_request("voice", Posture(seq=1, session="v", ts=1000.0 + clock.now,
                                   posture="stand").model_dump_json())
    assert sent(link)[-1]["type"] == "posture"


async def test_remote_posture_is_normal_once_awake(rig):
    gw, link, clock = rig
    gw.on_state(state("standing"))
    gw.on_request("remote", Posture(seq=1, session="r", ts=1000.0 + clock.now,
                                    posture="sit").model_dump_json())
    assert sent(link)[-1]["type"] == "posture"


async def test_status_is_retained_and_reports_each_source(rig):
    gw, link, clock = rig
    gw.on_request("voice", Heartbeat(ts=1000.0 + clock.now).model_dump_json())
    for _ in range(4):
        gw.tick()
    msg = [m for m in link.published if m.topic == T.gateway_status][-1]
    body = json.loads(msg.payload)
    assert body["sources"]["voice"]["alive"] and not body["sources"]["remote"]["alive"]
    assert link.hub.retained[T.gateway_status] == msg


async def test_snapshot_requests_still_pass_through(rig):
    gw, link, clock = rig
    gw.on_request("planner", Snapshot(seq=1, session="p", ts=1000.0 + clock.now,
                                      request_id="a").model_dump_json())
    assert sent(link)[-1]["type"] == "snapshot"


def test_config_holdoff_outlasts_a_renewal():
    assert GatewayConfig().stop_holdoff_s > 0.5
