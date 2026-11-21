import asyncio
import json

from spider_common.link import InMemoryHub
from spider_common.protocol import SayRequest, Topics

from spider_voice.gwclient import GatewayClient
from spider_voice.interfaces import RouterDecision, Transcript
from spider_voice.pipeline import VoicePipeline

ROBOT = "spider-01"
T = Topics(ROBOT)


class FakeSTT:
    async def transcribe(self, pcm16, sample_rate):
        return Transcript("", 0.0, 0.0)


class FakeRouter:
    async def route(self, transcript, on_act=None):
        return RouterDecision("none", "")


class FakeTTS:
    sample_rate = 16000

    def __init__(self):
        self.said = []

    async def synthesize(self, text):
        self.said.append(text)
        yield b"\x00\x00"


class FakeAudio:
    async def play(self, chunks, sample_rate):
        async for _ in chunks:
            pass
        return 0.01

    def cut(self):
        pass


async def rig(cfg):
    hub = InMemoryHub()
    link = hub.endpoint(GatewayClient.subscriptions(ROBOT))
    brain = hub.endpoint([T.voice_say])
    commands = hub.endpoint([T.request_filter])
    for endpoint in (link, brain, commands):
        await endpoint.start()
    gw = GatewayClient(link, ROBOT)
    tts = FakeTTS()
    pipe = VoicePipeline(cfg, stt=FakeSTT(), tts=tts, router=FakeRouter(), gateway=gw,
                         audio=FakeAudio())
    gw.on_say = lambda req: pipe.speak_remote(req.text, req.trace)
    runner = asyncio.create_task(gw.run())
    return pipe, tts, brain, commands, runner


async def test_valid_say_is_spoken_and_never_commands_motion(cfg):
    pipe, tts, brain, commands, runner = await rig(cfg)
    try:
        brain.publish(T.voice_say, SayRequest(trace="t1", text="شفت شي").model_dump_json())
        await asyncio.sleep(0.05)
        await pipe.drain()
        assert tts.said == ["شفت شي"]
        assert commands.inbox.queue.empty()
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_wrong_version_is_dropped(cfg):
    pipe, tts, brain, _commands, runner = await rig(cfg)
    try:
        bad = json.loads(SayRequest(trace="t1", text="لا تقول هاد").model_dump_json())
        bad["v"] = 99
        brain.publish(T.voice_say, json.dumps(bad))
        await asyncio.sleep(0.05)
        await pipe.drain()
        assert tts.said == []
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_say_is_dropped_while_the_voice_loop_is_busy(cfg):
    pipe, tts, brain, _commands, runner = await rig(cfg)
    try:
        pipe.echo.start_playback()
        brain.publish(T.voice_say, SayRequest(trace="t1", text="بعدين").model_dump_json())
        await asyncio.sleep(0.05)
        await pipe.drain()
        assert tts.said == []
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
