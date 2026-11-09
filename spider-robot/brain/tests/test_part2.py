"""Part 2: skills, memory, routing, vision fallback, voice, WhatsApp, Telegram + BrainService."""

import asyncio
import json
import shutil
import struct
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from spider_common.link import InMemoryHub
from test_brain import (
    FakeAnthropic,
    FakeVision,
    ScriptedPlanner,
    _Block,
    _sim_body,
    settings,
)

from spider_brain.calls import PlanStep, ToolCall, ToolOutcome
from spider_brain.memory import Memory
from spider_brain.planner import ClaudePlanner, RoutedPlanner
from spider_brain.robot_client import RobotClient
from spider_brain.service import BrainService, resolve_dirs
from spider_brain.skills import SkillLibrary
from spider_brain.tools import ToolExecutor
from spider_brain.vision import RoutedVision
from spider_brain.voice import VoiceService
from spider_brain.whatsapp import WhatsAppNotifier

BRAIN = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- skills
def test_skills_always_on_and_index(tmp_path):
    extra = tmp_path / "cv-writing-japan"
    (extra / "references").mkdir(parents=True)
    (extra / "SKILL.md").write_text("---\nname: cv-writing-japan\ndescription: CVs for Japan\n"
                                    "---\n\n# CV body\n", "utf-8")
    (extra / "references" / "rirekisho.md").write_text("rirekisho guide", "utf-8")
    lib = SkillLibrary([BRAIN / "skills", tmp_path], ["robot-reasoning", "robot-conversation"])
    text = lib.system_text()
    assert "<skill name=\"robot-reasoning\">" in text and "Robot conversation" in text
    assert "- cv-writing-japan: CVs for Japan" in text
    assert "rirekisho" in lib.load("cv-writing-japan")  # lists its references
    assert lib.load("cv-writing-japan", "rirekisho") == "rirekisho guide"
    assert "white" in lib.load("robot-conversation", "arabic")  # copied repo reference
    with pytest.raises(KeyError):
        lib.load("cv-writing-japan", "../../etc/passwd")  # only listed files
    with pytest.raises(KeyError):
        lib.load("nope")


def test_repo_skills_dir_resolves_to_repo_root():
    dirs = resolve_dirs(["skills", "../../skills"])
    assert dirs[0] == BRAIN / "skills"
    assert dirs[1] == (BRAIN / "../../skills").resolve()


# ----------------------------------------------------------------------------- memory
def test_memory_persists_and_recalls(tmp_path):
    m = Memory(tmp_path / "mem.jsonl")
    m.remember("The charging corner is left of the sofa", ["places"])
    m.remember("المالك يحب اللهجة الشامية", ["language"])
    again = Memory(tmp_path / "mem.jsonl")
    assert [f.text for f in again.recall("where is the charging corner")][0].startswith("The")
    assert again.recall("اللهجة")[0].tags == ["language"]
    assert again.forget(1) and not again.forget(99)
    assert len(Memory(tmp_path / "mem.jsonl").facts) == 1


async def test_skill_and_memory_tools(tmp_path):
    lib = SkillLibrary([BRAIN / "skills"], ["robot-reasoning"])
    ex = ToolExecutor(robot=None, vision=None, settings=settings(), bus=None, skills=lib,
                      memory=Memory(tmp_path / "m.jsonl"))
    out = await ex.run(ToolCall("1", "load_skill", {"name": "robot-conversation",
                                                     "reference": "arabic"}))
    assert not out.is_error and "Levantine" in out.text
    assert "Remembered" in (await ex.run(ToolCall("2", "remember",
                                                  {"fact": "Door is red", "tags": []}))).text
    assert "Door is red" in (await ex.run(ToolCall("3", "recall", {"query": "door"}))).text
    bad = await ex.run(ToolCall("4", "load_skill", {"name": "x", "reference": ""}))
    assert bad.is_error


# ----------------------------------------------------------------------------- routing
class FakePlanner:
    def __init__(self, route, fail=None):
        self.route, self.fail, self.cost_usd = route, fail, 0.0
        self.started, self.results = [], []

    def start(self, task):
        self.started.append(task)

    async def next_step(self):
        if self.fail:
            raise self.fail
        self.cost_usd += 0.1
        return PlanStep(text="", calls=[ToolCall("c", "get_status", {})])

    def add_results(self, results):
        self.results.extend(results)


async def test_router_falls_back_when_provider_is_down():
    made = {}

    def factory(route):
        made[route] = FakePlanner(route, httpx.ConnectError("down") if "opus" in route else None)
        return made[route]

    rp = RoutedPlanner(settings(), "default", context=lambda: "Mode: standing", factory=factory)
    rp.start("go to the door")
    step = await rp.next_step()
    assert step.calls and rp.route == "liquid"
    assert "Mode: standing" in made["liquid"].started[0]
    assert "go to the door" in made["liquid"].started[0]


async def test_router_escalates_simple_tier_after_errors():
    resp = SimpleNamespace(stop_reason="tool_use", usage=None, content=[
        _Block(type="tool_use", id="t", name="get_status", input={})])
    fake = FakeAnthropic([resp] * 4)
    s = settings()
    rp = RoutedPlanner(s, "simple", factory=lambda route: ClaudePlanner(
        s, client=fake, model=route.partition(":")[2]))
    rp.start("x")
    for _ in range(2):
        await rp.next_step()
        rp.add_results([(ToolCall("t", "get_status", {}), ToolOutcome("boom", is_error=True))])
    assert fake.calls[-1]["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in fake.calls[-1]  # Haiku has no server-side fallback
    await rp.next_step()
    assert fake.calls[-1]["model"] == "claude-opus-5-5" and rp.escalated
    assert fake.calls[-1]["fallbacks"] == "default"


async def test_router_budget_counts_all_models():
    rp = RoutedPlanner(settings(max_task_usd=0.25), "default",
                       factory=lambda route: FakePlanner(route))
    rp.start("x")
    await rp.next_step()
    await rp.next_step()
    await rp.next_step()  # 0.3 spent
    assert "budget" in (await rp.next_step()).text


# ----------------------------------------------------------------------------- vision, voice
class DownVision:
    async def ask(self, jpeg, q):
        raise httpx.ConnectError("vision server down")

    async def aclose(self):
        pass


async def test_vision_falls_back_to_backup():
    v = RoutedVision(DownVision(), FakeVision())
    assert "orange box" in await v.ask(b"\xff\xd8", "what?")


class FakeGemini:
    def __init__(self, pcm=b"", fail_tts=False):
        self.pcm, self.fail_tts = pcm, fail_tts
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._agen))
        self.models = SimpleNamespace(generate_content=self._gen)
        self.calls = []

    async def _agen(self, model, contents):
        self.calls.append(model)
        return SimpleNamespace(text=" روح لعند الباب ")

    def _gen(self, model, contents, config):
        if self.fail_tts:
            raise RuntimeError("tts down")
        part = SimpleNamespace(inline_data=SimpleNamespace(data=self.pcm))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])


async def test_voice_transcribe_uses_configured_model():
    g = FakeGemini()
    v = VoiceService(settings(gemini_api_key="k"), client=g)
    assert await v.transcribe(b"OggS...") == "روح لعند الباب"
    assert g.calls == ["gemini-2.5-flash"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_voice_speak_makes_ogg_with_real_ffmpeg():
    pcm = b"".join(struct.pack("<h", int(8000 * ((i // 40) % 2 * 2 - 1))) for i in range(24000))
    v = VoiceService(settings(gemini_api_key="k"), client=FakeGemini(pcm=pcm))
    audio = await v.speak("تمام، وصلت.")
    assert audio is not None and audio[1] == "ogg" and audio[0][:4] == b"OggS"


async def test_voice_degrades_to_text_only(monkeypatch):
    import gtts

    def broken(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(gtts.gTTS, "write_to_fp", broken)
    v = VoiceService(settings(gemini_api_key="k"), client=FakeGemini(fail_tts=True), ffmpeg="")
    assert await v.speak("hello") is None


# ----------------------------------------------------------------------------- WhatsApp
async def test_whatsapp_alert_uses_bridge_token_and_cooldown():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, req.headers.get("X-Bridge-Token"), json.loads(req.content)))
        return httpx.Response(200, json={"ok": True})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://bridge")
    wa = WhatsAppNotifier("http://bridge", "tok", cooldown_s=300, http=http)
    assert await wa.alert("fell over", "fallen")
    assert not await wa.alert("fell again", "fallen")  # cooldown: keep volume low
    assert seen == [("/send-voice-alert", "tok", {"text_caption": "fell over"})]


# ----------------------------------------------------------------------------- Telegram
class FakeTelegram:
    """Async Bot API stand-in: queued updates, recorded outgoing calls."""

    def __init__(self):
        self.updates: asyncio.Queue = asyncio.Queue()
        self.sent: list[tuple[str, dict]] = []
        self.n = 0

    async def handler(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        if req.url.path.startswith("/file/"):
            return httpx.Response(200, content=b"OggS-fake-voice")
        body = json.loads(req.content) if req.headers.get("content-type", "").startswith(
            "application/json") else {}
        if method == "getUpdates":
            try:
                u = await asyncio.wait_for(self.updates.get(), 0.05)
                return httpx.Response(200, json={"ok": True, "result": [u]})
            except TimeoutError:
                return httpx.Response(200, json={"ok": True, "result": []})
        if method == "getFile":
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "voice/1.oga"}})
        self.sent.append((method, body))
        self.n += 1
        return httpx.Response(200, json={"ok": True, "result": {"message_id": self.n}})

    def push(self, update):
        update.setdefault("update_id", self.updates.qsize() + 100 + len(self.sent))
        self.updates.put_nowait(update)

    def texts(self, chat=None):
        return [b.get("text", "") for m, b in self.sent
                if m == "sendMessage" and (chat is None or b.get("chat_id") == chat)]

    async def wait_for(self, pred, timeout=20.0):
        end = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < end:
            for item in self.sent:
                if pred(item):
                    return item
            await asyncio.sleep(0.05)
        raise AssertionError(f"not sent; got {self.sent}")


OWNER = 4242


def msg(text=None, uid=OWNER, voice=None):
    m = {"message_id": 1, "from": {"id": uid}, "chat": {"id": uid}}
    if text is not None:
        m["text"] = text
    if voice:
        m["voice"] = {"file_id": "f1", "mime_type": "audio/ogg"}
    return {"message": m}


async def test_telegram_owner_flow_with_approval_buttons_and_voice(tmp_path):
    hub = InMemoryHub()
    body, world, tasks = await _sim_body(hub, obstacles=[])
    tg = FakeTelegram()
    planners = []

    def factory(tier):
        p = ScriptedPlanner([("set_posture", {"posture": "stand"})])
        p.tier = tier
        planners.append(p)
        return p

    s = settings(autonomy="guarded", dashboard=False, telegram_token="T",
                 telegram_owner_ids=[OWNER], memory_path=str(tmp_path / "m.jsonl"))
    svc = BrainService(
        s, link=hub.endpoint(RobotClient.subscriptions("spider-01")), vision=FakeVision(),
        voice=VoiceService(s, client=FakeGemini(fail_tts=True), ffmpeg=""),
        planner_factory=factory,
        telegram_http=httpx.AsyncClient(transport=httpx.MockTransport(tg.handler),
                                        base_url="https://api.telegram.org"),
    )
    await svc.start()
    try:
        tg.push(msg("/status", uid=999))  # stranger: no reply at all
        tg.push(msg("/status"))
        await tg.wait_for(lambda m: m[0] == "sendMessage" and "Mode:" in m[1].get("text", ""))
        assert all(b.get("chat_id") != 999 for _, b in tg.sent)

        tg.push(msg(voice=True))  # voice note -> transcript -> task (simple tier)
        await tg.wait_for(lambda m: "🎤 روح لعند الباب" in m[1].get("text", ""))
        ask = await tg.wait_for(lambda m: "reply_markup" in m[1]
                                and "posture: stand" in m[1].get("text", ""))
        approve = ask[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        assert approve.endswith(":1")
        tg.push({"callback_query": {"id": "cq1", "from": {"id": OWNER}, "data": approve}})
        await tg.wait_for(lambda m: m[1].get("text") == "Finished the script.")
        assert planners[0].tier == "simple"
        assert "standing" in planners[0].results[0][1].text  # approved and executed
        assert body.mode == "standing"
    finally:
        await svc.stop()
        for t in tasks:
            t.cancel()
