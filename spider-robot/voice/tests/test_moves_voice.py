"""Expressive moves by voice: grammar only, never from the router, refused when negated."""

import pytest
from test_pipeline import FakeRouter, FakeSTT, rig, run_turn, sent

from spider_voice.actions import to_command
from spider_voice.grammar import CANNED_SAY, MOVE_ACTS, ROUTER_ACTS, acts_in, match
from spider_voice.interfaces import RouterDecision
from spider_voice.routing import cross_check, parse_decision
from spider_voice.stopwords import StopWords


@pytest.mark.parametrize(
    ("text", "act"),
    [("ارقص", "dance"), ("سلّم", "wave"), ("باي", "wave"), ("انحني", "bow"), ("المس", "reach"),
     ("وضع الهجوم", "attack_stance"), ("دافع", "defense_stance"),
     ("وضع الدفاع", "defense_stance"), ("انتبه", "alert"), ("نام", "sleep"),
     ("احتفل", "celebrate"), ("مرحبا", "hi"), ("هاي", "hi"), ("اهلا", "hi"),
     ("سلم علي", "offer_hand"), ("سلم عليّ", "offer_hand"), ("صافحني", "offer_hand"),
     ("مد ايدك", "offer_hand"), ("مد إيدك", "offer_hand")],
)
def test_grammar_maps_each_move(text, act):
    hit = match(text)
    assert hit is not None and hit.act == act and hit.say


def test_a_phrase_claims_its_words():
    assert acts_in("سلم علي") == {"offer_hand"}  # not wave as well
    assert acts_in("وضع الهجوم") == {"attack_stance"}
    assert acts_in("وضع") == set() and acts_in("الهجوم") == set()


def test_negated_or_mixed_moves_do_not_match():
    assert match("لا ترقص") is None
    assert match("ما تنام") is None
    assert match("ارقص وبعدين نام") is None  # two acts: not the grammar's to choose


def test_moves_are_not_router_acts():
    assert not MOVE_ACTS & set(ROUTER_ACTS)
    assert parse_decision('{"act": "dance", "say": "ok"}').act == "none"


def test_cross_check_refuses_a_move_the_owner_did_not_ask_for():
    assert cross_check(RouterDecision("dance", "x"), "كيف حالك").act == "none"
    assert cross_check(RouterDecision("dance", "x"), "لا ترقص").act == "none"
    assert cross_check(RouterDecision("dance", "x"), "ارقص شوي").act == "dance"


def test_each_move_act_becomes_one_command(cfg):
    for act in MOVE_ACTS:
        cmd = to_command(act, cfg.motion)
        assert cmd is not None and cmd.speed == 0.5
        if act == "reach":
            assert cmd.type == "reach" and cmd.target == "nearest"
        else:
            assert cmd.type == "perform" and cmd.name == act


def test_the_robot_never_says_a_move_command_or_a_stop_word():
    for act in MOVE_ACTS:
        say = CANNED_SAY[act]
        assert acts_in(say) == set(), (act, say)
        assert StopWords().match(say) is None, (act, say)


def test_khalas_variants_stop_the_move():
    assert StopWords().match("خلص") is not None  # one edit from خلاص
    assert StopWords().match("قف") is not None


async def test_dance_command_sends_perform_dance(cfg):
    router = FakeRouter()
    pipe, tts, _, obs, turns = await rig(cfg, FakeSTT("يا لوي ارقص"), router)
    await run_turn(pipe)
    out = sent(obs)
    assert len(out) == 1 and out[0]["type"] == "perform" and out[0]["name"] == "dance"
    assert out[0]["speed"] == 0.5 and out[0]["trace"] == turns[0].trace
    assert router.calls == 0 and turns[0].route == "grammar" and turns[0].act == "dance"


async def test_dont_dance_sends_nothing_even_if_the_router_says_dance(cfg):
    router = FakeRouter(RouterDecision("dance", "حاضر"))
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("لوي لا ترقص"), router)
    await run_turn(pipe)
    assert sent(obs) == [] and turns[0].act == "none"


async def test_a_move_needs_the_wake_word(cfg):
    pipe, _, _, obs, turns = await rig(cfg, FakeSTT("ارقص"))
    await run_turn(pipe)
    assert sent(obs) == [] and turns[0].reason == "no_wake_word"


async def test_handshake_and_stop(cfg):
    stt = FakeSTT("لوي صافحني")
    pipe, _, _, obs, _ = await rig(cfg, stt)
    await run_turn(pipe)
    assert sent(obs)[0]["name"] == "offer_hand"
    stt.result = type(stt.result)("خلص", -0.2, 0.1)
    await run_turn(pipe)
    assert [c["type"] for c in sent(obs)] == ["stop"]
