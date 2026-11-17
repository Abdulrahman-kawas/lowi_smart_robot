"""Hold to talk (/v1/talk): WAV checks, stop words before any model, and the route chain."""

import array
import asyncio
import io
import math
import wave

import pytest
from pydantic import ValidationError

from spider_brain.config import Settings
from spider_brain.mobile.talk import (
    STT_PROMPT_AR,
    TalkError,
    TalkService,
    collapse_repeats,
    loudest_rms,
    parse_wav,
    stop_kind,
)


def wav(seconds: float = 1.0, rate: int = 16_000, channels: int = 1, width: int = 2,
        amplitude: int = 3000) -> bytes:
    """A 220 Hz tone at speech level (amplitude 0: digital silence)."""
    n = int(seconds * rate)
    if width == 2:
        one = array.array("h", (int(amplitude * math.sin(2 * math.pi * 220 * i / rate))
                                for i in range(n)))
        frames = b"".join(bytes(one) for _ in range(channels))
    else:
        frames = b"\x80" * n * channels
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(width)
        out.setframerate(rate)
        out.writeframes(frames)
    return buf.getvalue()


class FakeEngine:
    def __init__(self, text: str) -> None:
        self.text, self.calls = text, []

    async def transcribe(self, pcm: bytes, language: str, prompt: str) -> tuple[str, float]:
        self.calls.append((len(pcm), prompt))
        return self.text, 0.9


class FakeRoute:
    def __init__(self, name: str, answer: str | Exception, delay_s: float = 0.0) -> None:
        self.name, self._answer, self.delay_s, self.questions = name, answer, delay_s, []

    async def answer(self, text: str, context: str) -> str:
        self.questions.append((text, context))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def service(heard: str, routes, **settings) -> tuple[TalkService, list[str]]:
    calls: list[str] = []
    s = Settings(_env_file=None, robot_source="planner", human_source="remote", **settings)
    svc = TalkService(s, stop=lambda who: calls.append(f"stop:{who}"),
                      estop=lambda who: calls.append(f"estop:{who}"),
                      context=lambda: "Robot state: mode relaxed.", engine=FakeEngine(heard),
                      routes=routes)
    return svc, calls


def test_only_16_khz_mono_16_bit_wav_up_to_the_limit_is_accepted():
    assert len(parse_wav(wav(1.0), 30.0)) == 32_000
    for bad in (wav(rate=44_100), wav(channels=2), wav(width=1), b"RIFF-not-a-wav"):
        with pytest.raises(TalkError) as exc:
            parse_wav(bad, 30.0)
        assert exc.value.status == 400
    with pytest.raises(TalkError) as exc:
        parse_wav(wav(31.0), 30.0)
    assert exc.value.status == 413


@pytest.mark.parametrize(("text", "kind", "rest"), [
    ("قف", "stop", 0), ("وقّف!", "stop", 0), ("STOP", "stop", 0), ("طوارئ قف", "estop", 0),
    ("شو الطقس اليوم", None, 3), ("قف بس بدي اسألك شو قدامك", "stop", 4),
])
def test_stop_words_match_like_the_robot_voice_loop(text, kind, rest):
    assert stop_kind(text) == (kind, rest)


async def test_a_stop_word_stops_before_any_model_runs():
    route = FakeRoute("liquid", "should not be asked")
    svc, calls = service("قف قف", [route])
    out = await svc.run("iPhone", wav())
    assert calls == ["stop:iPhone"] and route.questions == []
    assert out["action"] == "stop" and out["reply"] == "وقفت."


async def test_an_emergency_phrase_sends_estop():
    svc, calls = service("طوارئ", [FakeRoute("liquid", "x")])
    out = await svc.run("iPhone", wav())
    assert calls == ["estop:iPhone"] and out["action"] == "estop"


async def test_a_sentence_with_a_stop_word_stops_and_is_still_answered():
    route = FakeRoute("liquid", "قدامي طاولة.")
    svc, calls = service("قف بس بدي اسألك شو قدامك", [route])
    out = await svc.run("iPhone", wav())
    assert calls == ["stop:iPhone"]
    assert out["action"] == "stop" and out["reply"] == "وقفت. قدامي طاولة."


async def test_a_failed_route_falls_through_to_the_next_and_gets_the_robot_state():
    first = FakeRoute("anthropic:x", RuntimeError("down"))
    second = FakeRoute("liquid", "أهلا، كيفك؟")
    svc, calls = service("مرحبا لوي", [first, second])
    out = await svc.run("iPhone", wav())
    assert calls == [] and out["action"] == "answer" and out["reply"] == "أهلا، كيفك؟"
    assert out["provider"] == "whisper-small+liquid"
    assert second.questions == [("مرحبا لوي", "Robot state: mode relaxed.")]


async def test_no_route_that_answers_is_a_503_but_a_stop_still_goes_out():
    svc, _ = service("مرحبا", [FakeRoute("liquid", RuntimeError("down"))])
    with pytest.raises(TalkError) as exc:
        await svc.run("iPhone", wav())
    assert exc.value.status == 503 and "liquid" in str(exc.value)
    svc, calls = service("قف بس بدي اسألك شو قدامك", [FakeRoute("liquid", RuntimeError("down"))])
    out = await svc.run("iPhone", wav())
    assert calls == ["stop:iPhone"] and out["reply"] == "وقفت."


async def test_silence_answers_without_a_model():
    route = FakeRoute("liquid", "x")
    svc, calls = service("  ", [route])
    out = await svc.run("iPhone", wav())
    assert out["action"] == "no_speech" and route.questions == [] and calls == []


async def test_a_silent_clip_never_reaches_whisper():
    # With the stop-word prompt, Whisper turned 2 s of silence into "وقف، وقف، ..." on the server.
    svc, calls = service("وقف وقف وقف", [FakeRoute("liquid", "x")])
    out = await svc.run("iPhone", wav(2.0, amplitude=0))
    assert out["action"] == "no_speech" and out["provider"] == "silence"
    assert svc.engine.calls == [] and calls == []
    assert loudest_rms(b"\x00\x00" * 1600) == 0.0 and loudest_rms(b"") == 0.0


async def test_short_clips_are_padded_and_get_the_stop_word_prompt():
    svc, _ = service("قف", [])
    await svc.run("iPhone", wav(0.6))
    assert svc.engine.calls == [(int(0.6 * 16_000) * 2 + 32_000, STT_PROMPT_AR)]
    svc, _ = service("مرحبا", [FakeRoute("liquid", "أهلا")])
    await svc.run("iPhone", wav(3.0))
    assert svc.engine.calls == [(3 * 32_000, STT_PROMPT_AR)]  # long enough: no padding


def test_word_loops_are_cut():
    assert collapse_repeats("وقف وقف وقف وقف وقف وقف") == "وقف وقف وقف"
    assert collapse_repeats("نحن نحن نحن نحن نحن") == "نحن نحن نحن"
    assert collapse_repeats("مرحبا لوي شو عم تعمل") == "مرحبا لوي شو عم تعمل"


async def test_one_talk_at_a_time():
    svc, _ = service("مرحبا", [FakeRoute("liquid", "أهلا", delay_s=0.3)])
    first = asyncio.create_task(svc.run("iPhone", wav()))
    await asyncio.sleep(0.05)
    with pytest.raises(TalkError) as exc:
        await svc.run("iPad", wav())
    assert exc.value.status == 429
    assert (await first)["reply"] == "أهلا"


async def test_the_route_chain_has_one_deadline():
    svc, _ = service("مرحبا", [FakeRoute("slow", "late", delay_s=1.0), FakeRoute("liquid", "x")],
                     talk_timeout_s=0.2)
    with pytest.raises(TalkError) as exc:
        await svc.run("iPhone", wav())
    assert exc.value.status == 503


def test_talk_routes_are_validated():
    ok = Settings(_env_file=None, talk_routes="anthropic:claude-haiku-5-5, gemini:gemini-2.5-flash,"
                                              "compat:moonshotai/kimi-k3,lowi,liquid")
    routes = ok.talk_route_list
    assert routes[0] == "anthropic:claude-haiku-5-5" and routes[-1] == "liquid"
    for bad in ("openai", "compat:", "anthropic"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, talk_routes=bad)
