import pytest

from spider_voice.grammar import WakeGate, acts_in, match
from spider_voice.stopwords import StopWords
from spider_voice.text import edit_distance_at_most_one, normalize, tokens


def test_normalize_folds_arabic_variants_and_removes_marks():
    assert normalize("قِفْ!") == "قف"
    assert normalize("إلى الأمام، يا لوي") == "الي الامام يا لوي"
    assert normalize("STOP.") == "stop"
    assert tokens("  امشي   قدام ") == ["امشي", "قدام"]


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("قدام", "قدام", True), ("قدام", "قدم", True), ("قدام", "اقدام", True), ("قدام", "ورا", False),
     ("abcd", "abxy", False), ("", "a", True), ("", "ab", False)],
)
def test_edit_distance(a, b, expected):
    assert edit_distance_at_most_one(a, b) is expected


@pytest.mark.parametrize("text", ["قف", "وقف!", "يا روبوت وقف هلأ", "توقف", "ستوب", "stop", "خلاص"])
def test_stop_words_match_without_a_wake_word(text):
    assert StopWords().match(text) is not None


@pytest.mark.parametrize("text", ["امشي قدام", "شو اسمك", "الجو حلو اليوم", ""])
def test_ordinary_speech_is_not_a_stop(text):
    assert StopWords().match(text) is None


def test_emergency_outranks_stop_in_the_same_sentence():
    hit = StopWords().match("وقف طوارئ")
    assert hit is not None and hit.emergency


def test_robot_cannot_say_its_own_stop_words():
    assert StopWords().strip_from("حاضر رح اوقف هون") == "حاضر رح هون"
    assert StopWords().match(StopWords().strip_from("خلاص وقفت")) is None


@pytest.mark.parametrize(
    ("text", "act"),
    [("امشي قدام", "forward"), ("ارجع لورا", "back"), ("لف يمين", "right"), ("روح يسار", "left"),
     ("لف شمال", "left"), ("قوم", "stand"), ("اقعد", "sit"), ("شوف", "look")],
)
def test_grammar_maps_short_commands(text, act):
    hit = match(text)
    assert hit is not None and hit.act == act and hit.say


def test_grammar_refuses_ambiguity_and_long_sentences():
    assert match("لف يمين وبعدين يسار") is None  # two acts: let the router handle it
    assert match("امبارح كنت ماشي قدام البيت لما شفت جارنا وسلمت عليه") is None
    assert match("صباح الخير") is None


def test_acts_in_finds_only_what_was_said():
    assert acts_in("امشي قدام شوي") == {"forward"}
    assert acts_in("كيف حالك") == set()


def test_wake_gate_needs_the_word_then_opens_a_window():
    g = WakeGate(("لوي",), window_s=8.0)
    assert not g.accept("امشي قدام", now=0.0)
    assert g.accept("يا لوي امشي قدام", now=1.0)
    assert g.accept("لف يمين", now=5.0)
    assert not g.accept("لف يمين", now=9.5)


def test_wake_gate_extends_only_while_open_and_strips_the_word():
    g = WakeGate(("لوي",), window_s=8.0)
    g.extend(now=0.0)  # closed: must not open
    assert not g.accept("امشي", now=1.0)
    g.accept("لوي", now=2.0)
    g.extend(now=9.0)
    assert g.accept("امشي", now=16.0)
    assert g.remove_from("يا لوي امشي قدام") == "امشي قدام"
    assert g.remove_from("يا لوي") == ""


def test_disabled_gate_accepts_everything():
    assert WakeGate(("لوي",), 8.0, enabled=False).accept("امشي", 0.0)


def test_a_negated_command_is_not_a_grammar_hit():
    assert match("لا تمشي قدام") is None
    assert match("مش يمين") is None
    assert match("امشي قدام") is not None


def test_a_bare_walk_word_is_forward():
    assert match("امشي").act == "forward"
    assert match("ارجع").act == "back"
