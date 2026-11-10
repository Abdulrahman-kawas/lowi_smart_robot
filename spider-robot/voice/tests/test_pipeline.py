import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from spider_body.config import load_config
from spider_body.hw.camera import FakeCamera
from spider_body.hw.lidar import SimLidar, SimWorld
from spider_body.hw.servos import FakeServoBank
from spider_body.main import command_loop, control_loop, state_loop
from spider_body.robot import Robot
from spider_common.link import InMemoryHub
from spider_common.protocol import Move, Posture, Topics
from spider_gateway.gateway import Gateway

from spider_voice.adapters.stt_whisper import TranscribeTimeout
from spider_voice.gwclient import GatewayClient
from spider_voice.interfaces import RouterDecision, Transcript
from spider_voice.pipeline import VoicePipeline
from spider_voice.segmenter import Utterance

ROBOT = "spider-01"
T = Topics(ROBOT)
SIM_CFG = Path(__file__).resolve().parents[2] / "body" / "config" / "robot.sim.yaml"


class FakeSTT:
    def __init__(self, text, logprob=-0.2, no_speech=0.1, fail=False):
        self.result = Transcript(text, logprob, no_speech)
        self.fail = fail
        self.calls = 0

    async def transcribe(self, pcm16, sample_rate):
        self.calls += 1
        if self.fail:
            raise RuntimeError("stt down")
        return self.result


class FakeTTS:
    sample_rate = 16000

    def __init__(self, fail=False):
        self.said = []
        self.fail = fail

    async def synthesize(self, text):
        if self.fail:
            raise RuntimeError("tts down")
        self.said.append(text)
        yield b"\x00\x00"


class FakeRouter:
    def __init__(self, decision=None, fail=False):
        self.decision = decision or RouterDecision("none", "اهلا")
        self.fail = fail
        self.calls = 0

    async def route(self, transcript, on_act=None):
        self.calls += 1
        if self.fail:
            raise TimeoutError
        if on_act is not None and self.decision.act != "none":
            on_act(self.decision.act)
        return self.decision


class FakeAudio:
    def __init__(self):
        self.cuts = 0

    async def play(self, chunks, sample_rate):
        async for _ in chunks:
            pass
        return 0.01

    def cut(self):
        self.cuts += 1


class FakeVision:
    def __init__(self, answer="امشي قدام وقف"):
        self.answer_text = answer

    async def ask(self, question, trace):
        return self.answer_text


class FakeAnswerer:
    async def answer(self, question, trace):
        return "الجواب"


async def rig(cfg, stt, router=None, **kw):
    hub = InMemoryHub()
    link = hub.endpoint(GatewayClient.subscriptions(ROBOT))
    observer = hub.endpoint([T.request_filter])
    await link.start()
    await observer.start()
    gw = GatewayClient(link, ROBOT)
    tts = kw.pop("tts", FakeTTS())
    audio = FakeAudio()
    turns = []
    pipe = VoicePipeline(cfg, stt=stt, tts=tts, router=router or FakeRouter(), gateway=gw,
                         audio=audio, publish_turn=turns.append, **kw)
    return pipe, tts, audio, observer, turns


def sent(observer):
    out = []
    while not observer.inbox.queue.empty():
        out.append(json.loads(observer.inbox.queue.get_nowait().payload))
    return out


def utter(duration=0.8, during_playback=False, peak=500.0):
    return Utterance(b"\x00\x00" * 100, duration, peak, during_playback)


async def run_turn(pipe, utterance=None):
    pipe._dispatch(utterance or utter())
    await pipe.drain()


async def test_stop_word_stops_without_router_or_wake_word(cfg):
    router = FakeRouter()
    pipe, tts, audio, obs, turns = await rig(cfg, FakeSTT("وقف"), router)
    await run_turn(pipe)
    assert [c["type"] for c in sent(obs)] == ["stop"]
    assert router.calls == 0 and audio.cuts >= 1
    assert turns[0].route == "stop" and turns[0].trace
    assert tts.said == ["وقفت"]


async def test_stop_word_is_honoured_even_at_low_confidence(cfg):
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("قف", logprob=-5.0, no_speech=0.99))
    await run_turn(pipe)
    assert [c["type"] for c in sent(obs)] == ["stop"]


async def test_emergency_word_latches_estop(cfg):
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("طوارئ"))
    await run_turn(pipe)
    assert [c["type"] for c in sent(obs)] == ["estop"]
    assert turns[0].act == "estop"


async def test_background_speech_cannot_move_the_robot(cfg):
    router = FakeRouter()
    pipe, tts, _, obs, turns = await rig(cfg, FakeSTT("امشي قدام"), router)
    await run_turn(pipe)
    assert sent(obs) == [] and router.calls == 0 and tts.said == []
    assert turns[0].reason == "no_wake_word"


async def test_wake_word_then_grammar_moves_without_llm(cfg):
    router = FakeRouter()
    pipe, tts, _, obs, turns = await rig(cfg, FakeSTT("يا لوي امشي قدام"), router)
    await run_turn(pipe)
    move = sent(obs)[0]
    assert move["type"] == "move" and move["vx"] > 0 and move["duration_s"] <= 2.0
    assert move["trace"] == turns[0].trace
    assert router.calls == 0 and turns[0].route == "grammar" and tts.said
    assert turns[0].tts_first_ms == 10.0  # FakeAudio reports 0.01 s to first audio


async def test_attention_window_allows_a_follow_up(cfg):
    stt = FakeSTT("لوي امشي قدام")
    pipe, _, _, obs, _ = await rig(cfg, stt)
    await run_turn(pipe)
    sent(obs)
    stt.result = Transcript("لف يمين", -0.2, 0.1)
    await run_turn(pipe)
    assert sent(obs)[0]["wz"] < 0


async def test_low_confidence_is_ignored_unless_it_is_a_stop(cfg):
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("لوي امشي قدام", logprob=-3.0))
    await run_turn(pipe)
    assert sent(obs) == [] and turns[0].reason == "low_confidence"


async def test_own_voice_is_ignored(cfg):
    stt = FakeSTT("وقف")
    pipe, _, _, obs, turns = await rig(cfg, stt)
    pipe.echo.observe_echo(800.0)
    pipe.echo.alpha = 1.0
    pipe.echo.observe_echo(800.0)
    await run_turn(pipe, utter(during_playback=True, peak=900.0))
    assert stt.calls == 0 and sent(obs) == [] and turns[0].reason == "own_voice"


async def test_barge_in_can_stop_but_nothing_else(cfg):
    stt = FakeSTT("وقف")
    pipe, _, _, obs, _ = await rig(cfg, stt)
    await run_turn(pipe, utter(during_playback=True, peak=9000.0))
    assert [c["type"] for c in sent(obs)] == ["stop"]

    stt2 = FakeSTT("لوي امشي قدام")
    pipe2, _, _, obs2, turns2 = await rig(cfg, stt2)
    await run_turn(pipe2, utter(during_playback=True, peak=9000.0))
    assert sent(obs2) == [] and turns2[0].reason == "barge_in_without_stop_word"


async def test_llm_motion_must_match_the_words(cfg):
    router = FakeRouter(RouterDecision("forward", "رايح"))
    pipe, tts, _, obs, turns = await rig(cfg, FakeSTT("لوي كيف حالك اليوم يا صديقي العزيز الغالي"),
                                         router)
    await run_turn(pipe)
    assert sent(obs) == [] and turns[0].act == "none" and tts.said == ["رايح"]


async def test_llm_motion_with_matching_words_moves(cfg):
    router = FakeRouter(RouterDecision("left", "حاضر"))
    pipe, _, _, obs, _ = await rig(
        cfg, FakeSTT("لوي لو سمحت ممكن تلف يسار شوي لاني بدي اشوف"), router)
    await run_turn(pipe)
    assert sent(obs)[0]["wz"] > 0


async def test_router_failure_speaks_and_does_not_move(cfg):
    pipe, tts, _, obs, turns = await rig(cfg, FakeSTT("لوي احكيلي نكتة حلوة عن الروبوتات والناس"),
                                         FakeRouter(fail=True))
    await run_turn(pipe)
    assert sent(obs) == [] and turns[0].route == "failed" and tts.said


async def test_stt_failure_is_recorded(cfg):
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("", fail=True))
    await run_turn(pipe)
    assert sent(obs) == [] and turns[0].route == "failed" and pipe.failures == 1


async def test_only_the_newest_long_utterance_waits_and_a_short_stop_is_not_held_up(cfg):
    release = asyncio.Event()

    class Slow(FakeSTT):
        async def transcribe(self, pcm16, sample_rate):
            await release.wait()
            return await super().transcribe(pcm16, sample_rate)

    stt = Slow("وقف")
    pipe, _, _, obs, turns = await rig(cfg, stt)
    pipe._dispatch(utter(duration=4.0))  # runs
    await asyncio.sleep(0)
    pipe._dispatch(utter(duration=4.0))  # waits
    pipe._dispatch(utter(duration=4.0))  # replaces the one waiting
    assert turns[-1].reason == "stt_busy"
    pipe._dispatch(utter(duration=0.8))  # a short one still gets the free worker
    await asyncio.sleep(0)
    assert pipe._stt_running == 2
    release.set()
    await pipe.drain()
    assert stt.calls == 3 and len([c for c in sent(obs) if c["type"] == "stop"]) == 3


async def test_vision_answer_is_spoken_and_cannot_cause_motion(cfg):
    pipe, tts, _, obs, _ = await rig(cfg, FakeSTT("لوي شوف"), vision=[FakeVision()])
    await run_turn(pipe)
    assert all(c["type"] != "move" and c["type"] != "stop" for c in sent(obs))
    assert tts.said[0] == "لحظة أشوف"
    assert tts.said[1] == "امشي قدام"  # the injected stop word was removed before speaking


async def test_vision_failure_says_so(cfg):
    class Bad:
        async def ask(self, question, trace):
            raise TimeoutError

    pipe, tts, _, _, _ = await rig(cfg, FakeSTT("لوي شوف"), vision=[Bad()])
    await run_turn(pipe)
    assert tts.said[-1] == cfg.escalation.failure


async def test_a_question_escalates_and_the_answer_is_only_spoken(cfg):
    router = FakeRouter(RouterDecision("none", "ما بعرف"))
    pipe, tts, _, obs, turns = await rig(
        cfg, FakeSTT("لوي كيف بتشتغل البطارية تبعتك يا صديقي"), router, answerers=[FakeAnswerer()])
    await run_turn(pipe)
    assert turns[0].route == "escalate" and sent(obs) == []
    assert tts.said == [cfg.escalation.filler, "الجواب"]


async def test_low_confidence_escalates_stt_and_uses_the_better_text(cfg):
    escalate = FakeSTT("امشي قدام")
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("لوي شي مش واضح", logprob=-0.9),
                                       stt_escalate=escalate)
    await run_turn(pipe)
    assert escalate.calls == 1 and turns[0].route == "grammar"
    assert sent(obs)[0]["type"] == "move"


async def test_stop_word_silences_a_pending_vision_answer(cfg):
    release = asyncio.Event()

    class Slow:
        async def ask(self, question, trace):
            await release.wait()
            return "جواب متأخر"

    stt = FakeSTT("لوي شوف")
    pipe, tts, _, _, _ = await rig(cfg, stt, vision=[Slow()])
    pipe._dispatch(utter())
    await asyncio.sleep(0.02)
    stt.result = Transcript("وقف", -0.2, 0.1)
    pipe._dispatch(utter())
    await asyncio.sleep(0.02)
    release.set()
    await pipe.drain()
    assert "جواب متأخر" not in tts.said


async def test_unreachable_broker_is_reported_out_loud(cfg):
    pipe, tts, _, _, turns = await rig(cfg, FakeSTT("وقف"))
    pipe.gw.link.connected.clear()
    await run_turn(pipe)
    assert turns[0].reason == "broker_unreachable" and "الطاقة" in tts.said[0]


async def test_tts_falls_back_to_espeak(cfg):
    fallback = FakeTTS()
    pipe, _, _, _, _ = await rig(cfg, FakeSTT("x"), tts=FakeTTS(fail=True), tts_fallback=fallback)
    await pipe.speak("مرحبا")
    assert fallback.said == ["مرحبا"]


async def test_speech_onset_stop_is_off_by_default_and_works_when_enabled(cfg):
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("x"))
    pipe.gw.state, pipe.gw.state_rx = type("S", (), {"mode": "walking"})(), pipe.gw.clock()
    frame = b"\x00\x00" * 320
    for _ in range(8):
        pipe.on_frame(frame, True, 500.0)
    assert sent(obs) == []

    cfg2 = cfg.model_copy(update={"stop_on_speech_onset": True})
    pipe2, _, _, obs2, _ = await rig(cfg2, FakeSTT("x"))
    pipe2.gw.state, pipe2.gw.state_rx = type("S", (), {"mode": "walking"})(), pipe2.gw.clock()
    for _ in range(8):
        pipe2.on_frame(frame, True, 500.0)
    assert [c["type"] for c in sent(obs2)] == ["stop"]


# ------------------------------------------------------------------ through the real gateway+body

# ------------------------------------------------------------------ queueing and stale speech
class Gated(FakeSTT):
    """Transcribes when released, in order, and says what each utterance really was."""

    def __init__(self, texts):
        super().__init__("")
        self.texts = list(texts)
        self.gate = asyncio.Event()

    async def transcribe(self, pcm16, sample_rate):
        text = self.texts.pop(0)
        await self.gate.wait()
        self.calls += 1
        return Transcript(text, -0.2, 0.1)


async def test_a_stop_among_many_segments_always_reaches_the_gateway(cfg):
    stt = Gated(["شي", "وقف", "شي", "شي", "شي", "شي"])
    pipe, _, _, obs, _ = await rig(cfg, stt)
    for _ in range(6):
        pipe._dispatch(utter(duration=0.8))
    await asyncio.sleep(0)
    assert pipe._stt_running == cfg.stt.whisper_local.workers
    stt.gate.set()
    await pipe.drain()
    assert [c["type"] for c in sent(obs)] == ["stop"]
    assert pipe.dropped == 0


async def test_the_backlog_is_bounded_and_drops_the_oldest(cfg):
    cfg = cfg.model_copy(update={"max_short_queue": 2})
    stt = Gated(["شي"] * 12)
    pipe, _, _, _, turns = await rig(cfg, stt)
    for _ in range(6):
        pipe._dispatch(utter(duration=0.8))
    assert len(pipe._short_queue) == 2 and pipe.dropped == 2
    assert [t.reason for t in turns] == ["backlog", "backlog"]
    stt.gate.set()
    await pipe.drain()


async def test_a_stop_arriving_last_with_a_full_queue_is_transcribed_next(cfg):
    stt = Gated(["شي", "شي"])
    pipe, _, _, obs, _ = await rig(cfg, stt)
    for _ in range(2):
        pipe._dispatch(utter(duration=0.8))  # both workers busy
    await asyncio.sleep(0)
    for _ in range(3):
        pipe._dispatch(utter(duration=0.8))
    stt.texts = ["وقف", "شي", "شي"]  # what the newest, then older, utterances turn out to be
    await asyncio.sleep(0)
    stt.gate.set()
    await pipe.drain()
    assert [c["type"] for c in sent(obs)] == ["stop"]


async def test_a_long_utterance_never_takes_the_last_free_worker(cfg):
    stt = Gated(["شي", "شي", "شي"])
    pipe, *_ = await rig(cfg, stt)
    pipe._dispatch(utter(duration=0.8))  # one short running, one worker free
    pipe._dispatch(utter(duration=4.0))  # must wait: it would take the last worker
    await asyncio.sleep(0)
    assert pipe._stt_running == 1 and pipe._long_pending is not None
    stt.gate.set()
    await pipe.drain()
    assert pipe._long_pending is None and stt.calls == 2


class TimingOutSTT(FakeSTT):
    """Times out, while its thread keeps the worker until `running` is finished."""

    def __init__(self):
        super().__init__("")
        self.running = None

    async def transcribe(self, pcm16, sample_rate):
        self.running = asyncio.get_running_loop().create_future()
        raise TranscribeTimeout(self.running)


async def test_a_timed_out_transcription_keeps_its_slot_until_the_thread_ends(cfg):
    stt = TimingOutSTT()
    pipe, *_ = await rig(cfg, stt)
    pipe._dispatch(utter(duration=0.8))
    await pipe.drain()
    assert pipe._stt_running == 1 and pipe.stt_timeouts == 1
    stt.running.set_result(None)
    await asyncio.sleep(0)
    assert pipe._stt_running == 0


async def test_a_success_clears_the_timeout_count(cfg):
    pipe, *_ = await rig(cfg, FakeSTT("شي"))
    pipe.stt_timeouts = 2
    await run_turn(pipe)
    assert pipe.stt_timeouts == 0


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


async def test_a_motion_older_than_the_limit_sends_nothing(cfg):
    clock = FakeClock()
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("لوي امشي قدام"), clock=clock)
    old = replace(utter(), ended_at=clock.now - cfg.max_motion_age_s - 0.1)
    await run_turn(pipe, old)
    assert sent(obs) == [] and turns[-1].reason == "too_old"


async def test_a_stop_is_never_too_old(cfg):
    clock = FakeClock()
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("وقف"), clock=clock)
    await run_turn(pipe, replace(utter(), ended_at=clock.now - 600.0))
    assert [c["type"] for c in sent(obs)] == ["stop"]


async def test_a_fresh_motion_is_sent(cfg):
    clock = FakeClock()
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("لوي امشي قدام"), clock=clock)
    await run_turn(pipe, replace(utter(), ended_at=clock.now - 1.0))
    assert [c["type"] for c in sent(obs)] == ["move"]


# ------------------------------------------------------------------ streaming router
class StreamingRouter(FakeRouter):
    def __init__(self, early_act, decision):
        super().__init__(decision)
        self.early_act = early_act

    async def route(self, transcript, on_act=None):
        self.calls += 1
        on_act(self.early_act)
        return self.decision


async def test_a_stream_naming_a_motion_the_owner_did_not_say_sends_nothing(cfg):
    router = StreamingRouter("forward", RouterDecision("forward", "حاضر"))
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("لوي احكيلي نكتة حلوة اليوم يا صاحبي"), router)
    await run_turn(pipe)
    assert sent(obs) == []


async def test_an_early_act_is_sent_once_and_before_the_reply_ends(cfg):
    router = StreamingRouter("forward", RouterDecision("forward", "ماشي"))
    text = "لوي لو سمحت خلينا نمشي قدام شوي هلأ يا حبيبي"
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT(text), router)
    await run_turn(pipe)
    assert [c["type"] for c in sent(obs)] == ["move"]


async def test_a_stale_early_act_sends_nothing(cfg):
    clock = FakeClock()
    router = StreamingRouter("forward", RouterDecision("forward", "ماشي"))
    text = "لوي لو سمحت خلينا نمشي قدام شوي هلأ يا حبيبي"
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT(text), router, clock=clock)
    await run_turn(pipe, replace(utter(), ended_at=clock.now - cfg.max_motion_age_s - 1.0))
    assert sent(obs) == []


async def test_a_negated_motion_from_the_router_sends_nothing(cfg):
    router = StreamingRouter("forward", RouterDecision("forward", "حاضر"))
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("لوي لا تمشي قدام"), router)
    await run_turn(pipe)
    assert sent(obs) == []


async def test_speech_while_moving_is_cut_to_one_short_clause(cfg):
    say = "ماشي لقدام، وبعدين رح أشوف شو في حوالي بكل هدوء"
    router = StreamingRouter("forward", RouterDecision("forward", say))
    text = "لوي لو سمحت خلينا نمشي قدام شوي هلأ يا حبيبي"
    pipe, tts, _, _, _ = await rig(cfg, FakeSTT(text), router)
    await run_turn(pipe)
    assert tts.said == ["ماشي لقدام"]


# ------------------------------------------------------------------ the STT chain
async def test_a_grammar_hit_at_low_confidence_makes_no_server_call(cfg):
    escalate = FakeSTT("x")
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("لوي امشي قدام", logprob=-0.9),
                                   stt_escalate=escalate)
    await run_turn(pipe)
    assert escalate.calls == 0 and [c["type"] for c in sent(obs)] == ["move"]


async def test_a_stop_word_found_only_by_the_server_is_honoured(cfg):
    escalate = FakeSTT("وقف")
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("لوي شي مش واضح", logprob=-0.9),
                                       stt_escalate=escalate)
    await run_turn(pipe)
    assert [c["type"] for c in sent(obs)] == ["stop"] and turns[0].route == "stop"


async def test_prepare_renders_phrases_warms_the_router_and_reports_ready(cfg):
    router = FakeRouter()
    pipe, tts, _, _, _ = await rig(cfg, FakeSTT("x"), router)
    assert not pipe.ready
    await pipe.prepare()
    assert pipe.ready and router.calls == 1
    assert "وقفت" in pipe.canned and cfg.escalation.filler in pipe.canned
    said = len(tts.said)
    await pipe.speak("وقفت")
    assert len(tts.said) == said  # played from the rendered copy, no synthesis


async def test_prepare_survives_a_dead_router(cfg):
    pipe, *_ = await rig(cfg, FakeSTT("x"), FakeRouter(fail=True))
    await pipe.prepare()
    assert pipe.ready


async def test_speech_onset_stop_has_a_cooldown_and_ignores_own_speech(cfg):
    cfg = cfg.model_copy(update={"stop_on_speech_onset": True})
    clock = FakeClock()
    pipe, _, _, obs, _ = await rig(cfg, FakeSTT("x"), clock=clock)
    pipe.gw.clock = clock
    pipe.gw.state, pipe.gw.state_rx = type("S", (), {"mode": "walking"})(), clock.now
    pipe._on_speech_onset(clock.now, playing=True)
    assert sent(obs) == []
    pipe._on_speech_onset(clock.now, playing=False)
    pipe._on_speech_onset(clock.now + 0.2, playing=False)
    assert [c["type"] for c in sent(obs)] == ["stop"]


@pytest.fixture
async def full_stack():
    body_cfg = load_config(SIM_CFG, calibration="/nonexistent")
    body_cfg.gait.posture_speed_mps = 0.5
    hub = InMemoryHub()
    world = SimWorld(obstacles=[])
    body_link = hub.endpoint([T.cmd])
    robot = Robot(body_cfg, FakeServoBank(), SimLidar(body_cfg.lidar, world),
                  FakeCamera(body_cfg.camera), body_link)
    gw_link = hub.endpoint(Gateway.subscriptions(ROBOT))
    voice_link = hub.endpoint(GatewayClient.subscriptions(ROBOT))
    for link in (body_link, gw_link, voice_link):
        await link.start()
    gateway = Gateway(gw_link, ROBOT)
    client = GatewayClient(voice_link, ROBOT)
    tasks = [asyncio.create_task(c) for c in (
        control_loop(robot, world), command_loop(robot, body_link), state_loop(robot, body_link),
        robot.lidar.run(), gateway.run(tick_hz=20.0), client.run(), client.heartbeat_loop(10.0))]
    yield robot, client, world
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def _until(condition, timeout_s):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


async def test_spoken_command_walks_and_spoken_stop_halts_the_simulated_robot(cfg, full_stack):
    robot, client, world = full_stack
    stt = FakeSTT("لوي امشي قدام")
    pipe = VoicePipeline(cfg, stt=stt, tts=FakeTTS(), router=FakeRouter(), gateway=client,
                         audio=FakeAudio())
    client.send(Posture(posture="stand"))
    assert await _until(lambda: robot.mode == "standing" and robot._height_reached(), 5.0)
    await run_turn(pipe)
    assert await _until(lambda: robot.move is not None, 2.0)
    assert isinstance(robot.move, Move) and robot.move.trace

    stt.result = Transcript("وقف", -0.2, 0.1)
    started = time.monotonic()
    await run_turn(pipe)
    assert await _until(lambda: robot.move is None, 1.0)
    assert time.monotonic() - started < 0.5  # software path only: STT latency is a separate budget
