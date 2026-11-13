import asyncio
import base64
import json
import math
import sys
import threading
import time
import types

import httpx
import pytest
from spider_common.link import InMemoryHub
from spider_common.protocol import AskReply, SttReply, SttRequest, Topics

from spider_voice.adapters.ask_rpc import RpcAsk
from spider_voice.adapters.router_ollama import OllamaRouter
from spider_voice.adapters.stt_chain import ServerFirstSTT
from spider_voice.adapters.stt_rpc import RpcStt, ServerUnavailable
from spider_voice.adapters.stt_whisper import TranscribeTimeout, WhisperLocalSTT
from spider_voice.adapters.tts_espeak import strip_wav_header
from spider_voice.adapters.tts_piper import PiperTTS
from spider_voice.audio import frame_rms, is_speech_frame
from spider_voice.config import PiperCfg, RouterCfg, WhisperLocalCfg
from spider_voice.interfaces import RouterDecision, Transcript
from spider_voice.routing import (
    FALLBACK_SAY,
    MAX_SAY_CHARS,
    NUM_CTX,
    NUM_PREDICT,
    SCHEMA,
    cross_check,
    parse_decision,
)
from spider_voice.rpc import RpcClient


def test_parse_valid_decision():
    d = parse_decision(json.dumps({"act": "forward", "say": "حاضر"}))
    assert d == RouterDecision("forward", "حاضر")


@pytest.mark.parametrize(
    "raw",
    ['{"act": "forward", "say": "حا', "not json", "[1,2]", '{"act": "fly", "say": "x"}',
     '{"act": "forward"}', '{"act": "forward", "say": 3}', None],
)
def test_anything_unparsable_means_no_action(raw):
    assert parse_decision(raw) == RouterDecision("none", FALLBACK_SAY)


def test_say_is_truncated():
    assert len(parse_decision(json.dumps({"act": "none", "say": "ا" * 500})).say) == 60


def test_router_cannot_invent_a_motion():
    d = cross_check(RouterDecision("forward", "رايح"), "كيف حالك اليوم")
    assert d.act == "none" and d.say == "رايح"


def test_router_motion_matching_the_words_is_kept():
    assert cross_check(RouterDecision("left", "ok"), "لو سمحت لف يسار شوي").act == "left"


def test_non_motion_acts_do_not_need_a_lexical_match():
    assert cross_check(RouterDecision("look", "لحظة"), "ايش هذا").act == "look"
    assert cross_check(RouterDecision("none", "اهلا"), "مرحبا").act == "none"


def test_schema_and_token_limit():
    assert SCHEMA["properties"]["act"]["enum"][-1] == "none"
    assert SCHEMA["properties"]["say"]["maxLength"] == MAX_SAY_CHARS == 60
    # Measured worst case: 0.78 tokens per Arabic character, plus 12 for the JSON wrapper.
    assert NUM_PREDICT >= int(MAX_SAY_CHARS * 0.78) + 12


def _mock(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _stream(*pieces):
    return "\n".join(json.dumps({"message": {"content": p}}) for p in pieces) + "\n"


async def test_ollama_request_shape():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, text=_stream('{"act":"none",', '"say":"اهلا"}'))

    router = OllamaRouter(RouterCfg(), http=_mock(handler))
    assert (await router.route("مرحبا")).say == "اهلا"
    assert seen["format"] == SCHEMA and seen["keep_alive"] == -1 and seen["stream"] is True
    assert seen["options"]["temperature"] == 0.1 and seen["options"]["num_predict"] == NUM_PREDICT
    assert seen["options"]["num_thread"] == 3 and seen["options"]["num_ctx"] == NUM_CTX


async def test_ollama_reports_the_act_once_as_soon_as_it_is_readable():
    seen = []

    def handler(request):
        return httpx.Response(200, text=_stream('{"act":"for', 'ward","say":"', 'حاضر"}'))

    router = OllamaRouter(RouterCfg(), http=_mock(handler))
    decision = await router.route("امشي", seen.append)
    assert seen == ["forward"] and decision == RouterDecision("forward", "حاضر")


async def test_ollama_ignores_an_act_outside_the_list():
    seen = []

    def handler(request):
        return httpx.Response(200, text=_stream('{"act":"jump","say":"x"}'))

    router = OllamaRouter(RouterCfg(), http=_mock(handler))
    assert (await router.route("x", seen.append)).act == "none" and seen == []


async def test_ollama_times_out_as_a_whole():
    class Hanging(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(5)
            yield b""

    def handler(request):
        return httpx.Response(200, stream=Hanging())

    router = OllamaRouter(RouterCfg(timeout_s=0.05), http=_mock(handler))
    with pytest.raises(TimeoutError):
        await router.route("x")


async def test_ollama_server_error_raises():
    router = OllamaRouter(RouterCfg(), http=_mock(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        await router.route("x")


async def _rpc_rig():
    hub = InMemoryHub()
    link = hub.endpoint([])
    await link.start()
    return RpcClient(link, "r1"), link, Topics("r1")


async def test_server_stt_sends_base64_pcm_and_answers():
    rpc, link, t = await _rpc_rig()
    stt = RpcStt(rpc, timeout_s=1.0)
    task = asyncio.create_task(stt.transcribe(b"\x01\x00", 16000))
    await asyncio.sleep(0)
    req = SttRequest.model_validate_json(link.published[0].payload)
    assert link.published[0].topic == t.rpc_request("stt")
    assert base64.b64decode(req.audio_b64) == b"\x01\x00"
    rpc.on_reply(req.trace, SttReply(trace=req.trace, ok=True, text="قدام",
                                     confidence=0.5).model_dump_json().encode())
    out = await task
    assert out.text == "قدام" and out.avg_logprob == pytest.approx(math.log(0.5))


async def test_a_hanging_server_costs_only_one_timeout():
    rpc, link, _ = await _rpc_rig()
    now = [0.0]
    stt = RpcStt(rpc, timeout_s=0.01, retry_after_s=30.0, clock=lambda: now[0])
    with pytest.raises(TimeoutError):
        await stt.transcribe(b"\0\0", 16000)
    started = time.perf_counter()
    with pytest.raises(ServerUnavailable):
        await stt.transcribe(b"\0\0", 16000)
    assert time.perf_counter() - started < 0.005
    assert len(link.published) == 1  # the second utterance did not even ask
    now[0] = 31.0
    with pytest.raises(TimeoutError):
        await stt.transcribe(b"\0\0", 16000)
    assert len(link.published) == 2  # the breaker tries again later


async def test_server_stt_failure_raises():
    rpc, link, _ = await _rpc_rig()
    stt = RpcStt(rpc, timeout_s=1.0)
    task = asyncio.create_task(stt.transcribe(b"\0\0", 16000))
    await asyncio.sleep(0)
    req = SttRequest.model_validate_json(link.published[0].payload)
    rpc.on_reply(req.trace, SttReply(trace=req.trace, ok=False, error="busy")
                 .model_dump_json().encode())
    with pytest.raises(RuntimeError, match="busy"):
        await task


async def test_ask_returns_text_only():
    rpc, link, t = await _rpc_rig()
    ask = RpcAsk(rpc, timeout_s=1.0, need_image=True)
    task = asyncio.create_task(ask.ask("شو شايف", "tr1"))
    await asyncio.sleep(0)
    assert link.published[0].topic == t.rpc_request("ask")
    assert json.loads(link.published[0].payload)["need_image"] is True
    rpc.on_reply("tr1", AskReply(trace="tr1", ok=True, text="كرسي").model_dump_json().encode())
    assert await task == "كرسي"


async def test_ask_with_no_answer_raises():
    rpc, _, _ = await _rpc_rig()
    ask = RpcAsk(rpc, timeout_s=1.0, need_image=False)
    task = asyncio.create_task(ask.answer("كيف", "tr2"))
    await asyncio.sleep(0)
    rpc.on_reply("tr2", AskReply(trace="tr2", ok=False, error="busy").model_dump_json().encode())
    with pytest.raises(RuntimeError, match="busy"):
        await task


def test_quiet_frames_are_never_speech():
    assert is_speech_frame(True, 1000.0, -45.0)
    assert not is_speech_frame(True, 10.0, -45.0)  # about -70 dBFS
    assert not is_speech_frame(True, 0.0, -45.0)
    assert not is_speech_frame(False, 1000.0, -45.0)


def test_whisper_loads_once_when_constructed(monkeypatch):
    created = []

    class Model:
        def __init__(self, *args, **kwargs):
            created.append(args)

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Model))
    stt = WhisperLocalSTT(WhisperLocalCfg())
    assert len(created) == 1 and isinstance(stt._model, Model)


class _Segment:
    def __init__(self, text, lp, ns):
        self.text, self.avg_logprob, self.no_speech_prob = text, lp, ns


class _FakeWhisper:
    def __init__(self, segments):
        self.segments = segments
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        self.audio = audio
        return iter(self.segments), None


async def test_local_whisper_adapter_merges_segments():
    model = _FakeWhisper([_Segment(" امشي", -0.2, 0.1), _Segment(" قدام", -0.4, 0.3)])
    out = await WhisperLocalSTT(WhisperLocalCfg(), model=model).transcribe(b"\x00\x40" * 10, 16000)
    assert out.text == "امشي قدام"
    assert out.avg_logprob == pytest.approx(-0.3) and out.no_speech_prob == 0.3
    assert model.kwargs["language"] == "ar" and model.kwargs["beam_size"] == 1
    assert model.kwargs["condition_on_previous_text"] is False
    assert model.audio.max() == pytest.approx(0.5)


async def test_local_whisper_with_no_segments_is_no_speech():
    stt = WhisperLocalSTT(WhisperLocalCfg(), model=_FakeWhisper([]))
    out = await stt.transcribe(b"\0\0", 16000)
    assert out.text == "" and out.no_speech_prob == 1.0


async def test_local_whisper_rejects_the_wrong_rate():
    with pytest.raises(ValueError):
        await WhisperLocalSTT(WhisperLocalCfg(), model=_FakeWhisper([])).transcribe(b"", 8000)


async def test_piper_adapter_streams_chunks_and_surfaces_errors():
    class Chunk:
        def __init__(self, data):
            self.audio_int16_bytes = data

    class Voice:
        def synthesize(self, text):
            yield Chunk(b"ab")
            yield Chunk(b"cd")

    class Broken:
        def synthesize(self, text):
            raise RuntimeError("bad model")
            yield

    assert [c async for c in PiperTTS(PiperCfg(), voice=Voice()).synthesize("x")] == [b"ab", b"cd"]
    with pytest.raises(RuntimeError):
        [c async for c in PiperTTS(PiperCfg(), voice=Broken()).synthesize("x")]


def test_espeak_header_is_stripped():
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 20 + b"data\xff\xff\xff\xff" + b"PCM"
    assert strip_wav_header(wav) == b"PCM"
    with pytest.raises(ValueError):
        strip_wav_header(b"not a wav")


def test_frame_rms():
    assert frame_rms(b"") == 0.0
    assert frame_rms(b"\x10\x27\xf0\xd8") == pytest.approx(10000.0)


class _Named:
    def __init__(self, text=None):
        self.text, self.calls = text, 0

    async def transcribe(self, pcm16, sample_rate):
        self.calls += 1
        if self.text is None:
            raise ServerUnavailable("down")
        return Transcript(self.text)


async def test_server_first_uses_the_server_when_it_answers():
    server, local = _Named("من السيرفر"), _Named("محلي")
    out = await ServerFirstSTT(server, local).transcribe(b"", 16000)
    assert out.text == "من السيرفر" and local.calls == 0


async def test_server_first_falls_back_to_local():
    server, local = _Named(None), _Named("محلي")
    assert (await ServerFirstSTT(server, local).transcribe(b"", 16000)).text == "محلي"


async def test_whisper_timeout_leaves_a_handle_on_the_running_thread():
    release = threading.Event()

    class Slow(_FakeWhisper):
        def transcribe(self, audio, **kwargs):
            release.wait(2.0)
            return super().transcribe(audio, **kwargs)

    stt = WhisperLocalSTT(WhisperLocalCfg(timeout_s=0.01), model=Slow([]))
    with pytest.raises(TranscribeTimeout) as caught:
        await stt.transcribe(b"\0\0", 16000)
    assert not caught.value.running.done()
    release.set()
    await caught.value.running


def test_whisper_timeout_default_allows_for_a_slow_pi():
    assert WhisperLocalCfg().timeout_s >= 20.0
