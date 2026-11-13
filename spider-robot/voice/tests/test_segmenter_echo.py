from spider_voice.echo import EchoGate
from spider_voice.segmenter import Segmenter

FRAME = b"\x00\x00" * 320


def feed(seg, pattern, rms=100.0, playing=False):
    out = []
    for is_speech in pattern:
        u = seg.push(FRAME, is_speech, rms, playing)
        if u is not None:
            out.append(u)
    return out


def test_ends_after_the_silence_hangover():
    s = Segmenter(frame_ms=20, end_ms=300)
    done = feed(s, [True] * 30 + [False] * 14)
    assert done == []
    done = feed(s, [False])
    assert len(done) == 1 and done[0].duration_s > 0.6


def test_a_click_is_not_an_utterance():
    assert feed(Segmenter(), [True] * 3 + [False] * 40) == []


def test_short_utterance_below_minimum_is_dropped():
    s = Segmenter(frame_ms=20, start_frames=2, end_ms=100, min_utterance_ms=400)
    assert feed(s, [True] * 5 + [False] * 10) == []


def test_preroll_keeps_the_start_of_the_word():
    s = Segmenter(frame_ms=20, end_ms=100, preroll_ms=200)
    feed(s, [False] * 20)
    done = feed(s, [True] * 10 + [False] * 6)
    assert done[0].duration_s >= (10 + 5) * 0.02  # pre-roll frames are included


def test_max_length_cuts_a_never_ending_utterance():
    s = Segmenter(frame_ms=20, max_utterance_s=1.0)
    assert len(feed(s, [True] * 200)) >= 1


def test_overlap_with_playback_is_flagged():
    s = Segmenter(frame_ms=20, end_ms=100)
    done = feed(s, [True] * 10 + [False] * 6, playing=True)
    assert done[0].during_playback


def test_echo_gate_tail_and_barge_in_threshold():
    g = EchoGate(tail_s=0.25, barge_in_margin_db=9.0, alpha=1.0)
    g.start_playback()
    assert g.playing(0.0)
    g.observe_echo(1000.0)
    assert not g.is_barge_in(1500.0)
    assert g.is_barge_in(3000.0)  # about 9.5 dB above the robot's own voice
    g.stop_playback(10.0)
    assert g.playing(10.2) and not g.playing(10.3)
