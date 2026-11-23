"""The voice loop: microphone frames in, stop / move / speak out.

Order for every utterance, cheapest and most important first:

  1. stop words on the transcript        no wake word, no confidence check, no model
  2. quality and wake-word gates         background speech ends here
  3. closed-vocabulary grammar           common commands, no model
  4. better STT on the server            only for an unsure utterance the grammar did not match
  5. LLM router                          everything else; a motion must match the owner's words
  6. server or cloud                     spoken only; these answers can never cause motion

Sending a command is a non-blocking publish, so motion and speech start together.

Whisper takes seconds on a Pi 4, so utterances do pile up. Short ones (every Stop is short) take
turns on the STT workers and a long one may never occupy the last free worker, so a Stop waits for
at most one short utterance. A motion from speech that has grown too old is discarded; a Stop never.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

from spider_common.obs import Histogram, Stopwatch, new_trace
from spider_common.protocol import VoiceRoute, VoiceTurn

from .actions import to_command
from .config import VoiceConfig
from .echo import EchoGate
from .grammar import CANNED_SAY, LOOK_ACTS, MOTION_ACTS, MOVE_ACTS, WakeGate, match
from .gwclient import GatewayClient
from .interfaces import STT, TTS, Answerer, AudioOut, Router, RouterDecision, Transcript, Vision
from .routing import cross_check
from .segmenter import Segmenter, Utterance
from .stopwords import StopWords
from .text import tokens

log = logging.getLogger(__name__)

SAY_STOPPED = "وقفت"
SAY_STOP_FAILED = "ما قدرت أوقف، اقطع الطاقة"
SAY_YES = "نعم"
SAY_DONE = "حاضر"
SAY_THINK_FAILED = "ما قدرت أفكر هلأ"
MAX_SPOKEN_CHARS = 300
_POSTURE_ACTS = frozenset({"stand", "sit"})
_CLAUSE = re.compile(r"[،,.!؟?؛;]")
QUESTION_WORDS = frozenset(
    tokens("ليش كيف ايش شو مين وين هل لماذا ماذا متى كم what why how who where when")
)


def short_clause(text: str, max_chars: int) -> str:
    """The first clause only, cut at a word: long speech while moving leaves the robot deaf."""
    clause = _CLAUSE.split(text, maxsplit=1)[0].strip()
    return clause[:max_chars].rsplit(" ", 1)[0] if len(clause) > max_chars else clause


class VoicePipeline:
    def __init__(
        self,
        cfg: VoiceConfig,
        *,
        stt: STT,
        tts: TTS,
        router: Router,
        gateway: GatewayClient,
        audio: AudioOut,
        tts_fallback: TTS | None = None,
        stt_escalate: STT | None = None,
        vision: list[Vision] | None = None,
        answerers: list[Answerer] | None = None,
        publish_turn: Callable[[VoiceTurn], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.stt, self.tts, self.router, self.gw, self.audio = stt, tts, router, gateway, audio
        self.tts_fallback, self.stt_escalate = tts_fallback, stt_escalate
        self.vision = vision or []
        self.answerers = answerers or []
        self.publish_turn = publish_turn
        self.clock = clock
        a = cfg.audio
        self.segmenter = Segmenter(frame_ms=a.frame_ms, end_ms=a.end_of_speech_ms,
                                   max_utterance_s=a.max_utterance_s)
        self.echo = EchoGate()
        self.stop_words = StopWords(cfg.stop_words, cfg.emergency_words)
        self.wake = WakeGate(cfg.wake_words, cfg.attention_window_s, cfg.wake_required)
        self._long_busy = False
        self._long_pending: tuple[Utterance, str] | None = None  # the newest long one waiting
        self._short_queue: deque[tuple[Utterance, str]] = deque()
        self._stt_running = 0
        self._last_onset_stop = -1e9
        self.canned: dict[str, tuple[bytes, int]] = {}
        self.ready = False
        self.dropped = 0
        self.stt_timeouts = 0  # in a row; a slow Pi loses every command, Stop included
        self._speech_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._escalations: set[asyncio.Task] = set()  # a stop word silences these
        self.stt_hist = Histogram()
        self.route_hist = Histogram()
        self.total_hist = Histogram()
        self.turns = 0
        self.failures = 0

    # ------------------------------------------------------------------ frames
    def on_frame(self, frame: bytes, is_speech: bool, rms: float) -> None:
        """Called once per microphone frame from the capture loop. Never waits for anything."""
        now = self.clock()
        playing = self.echo.playing(now)
        if playing:
            self.echo.observe_echo(rms)
        before = self.segmenter.in_speech
        utterance = self.segmenter.push(frame, is_speech, rms, playing)
        if not before and self.segmenter.in_speech:
            self._on_speech_onset(now, playing)
        if utterance is not None:
            self._dispatch(replace(utterance, ended_at=now))

    def _on_speech_onset(self, now: float, playing: bool) -> None:
        """Optional: stop before any model has run. Off until bench V4 shows gait noise is safe."""
        cooled = now - self._last_onset_stop >= self.cfg.speech_onset_cooldown_s
        if self.cfg.stop_on_speech_onset and self.gw.walking and not playing and cooled:
            self._last_onset_stop = now
            self.gw.stop(new_trace())

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _spawn_escalation(self, coro) -> None:
        task = self._spawn(coro)
        self._escalations.add(task)
        task.add_done_callback(self._escalations.discard)

    def _dispatch(self, utterance: Utterance) -> None:
        trace = new_trace()
        if utterance.during_playback and not self.echo.is_barge_in(utterance.peak_rms):
            self._record(trace, "ignored", reason="own_voice", audio_s=utterance.duration_s)
            return
        if utterance.duration_s <= self.cfg.audio.short_utterance_s or utterance.during_playback:
            if len(self._short_queue) >= self.cfg.max_short_queue:
                old, old_trace = self._short_queue.popleft()
                self.dropped += 1
                self._record(old_trace, "ignored", reason="backlog", audio_s=old.duration_s)
            self._short_queue.append((utterance, trace))
        else:
            if self._long_pending is not None:  # the newest long utterance wins the waiting slot
                old, old_trace = self._long_pending
                self.dropped += 1
                self._record(old_trace, "ignored", reason="stt_busy", audio_s=old.duration_s)
            self._long_pending = (utterance, trace)
        self._schedule()

    def _schedule(self) -> None:
        """Start whatever may start. A long utterance never takes the last free STT worker."""
        workers = self.cfg.stt.whisper_local.workers
        while self._stt_running < workers and self._short_queue:
            utterance, trace = self._short_queue.pop()  # newest first: old speech is going stale
            self._stt_running += 1
            self._spawn(self.turn(utterance, trace, self._stt_finished))
        if (self._long_pending is not None and not self._long_busy
                and self._stt_running < max(1, workers - 1)):
            utterance, trace = self._long_pending
            self._long_pending = None
            self._long_busy = True
            self._stt_running += 1
            self._spawn(self.turn(utterance, trace, self._long_stt_finished))

    def _stt_finished(self) -> None:
        self._stt_running -= 1
        self._schedule()

    def _long_stt_finished(self) -> None:
        self._long_busy = False
        self._stt_finished()

    def _too_old(self, utterance: Utterance) -> bool:
        return (utterance.ended_at is not None
                and self.clock() - utterance.ended_at > self.cfg.max_motion_age_s)

    # ------------------------------------------------------------------ one utterance
    async def turn(
        self, utterance: Utterance, trace: str, on_stt_done: Callable[[], None] | None = None
    ) -> None:
        total = Stopwatch()
        watch = Stopwatch()
        audio_s = utterance.duration_s
        release = on_stt_done
        try:
            heard = await self.stt.transcribe(utterance.pcm16, self.cfg.audio.sample_rate)
            self.stt_timeouts = 0
        except Exception as exc:  # STT failed; motion and stop words stay unaffected next time
            log.warning("stt failed: %r", exc)
            self.failures += 1
            if isinstance(exc, TimeoutError):
                self.stt_timeouts += 1
            running = getattr(exc, "running", None)
            if running is not None and release is not None:  # busy until the thread ends
                running.add_done_callback(lambda _future: on_stt_done())
                release = None
            self._record(trace, "failed", reason="stt", audio_s=audio_s)
            return
        finally:
            if release is not None:  # the worker is free as soon as the text exists
                release()
        stt_ms = watch.ms()
        self.stt_hist.record(stt_ms)
        text = heard.text.strip()

        if self._honour_stop(text, text, trace, stt_ms, total, audio_s):
            return
        if utterance.during_playback:
            self._record(trace, "ignored", text, reason="barge_in_without_stop_word",
                         stt_ms=stt_ms, audio_s=audio_s)
            return
        if not self._acceptable(text, heard):
            self._record(trace, "ignored", text, reason="low_confidence", stt_ms=stt_ms,
                         audio_s=audio_s)
            return

        heard_wake = self.wake.accept(text, self.clock())
        if not heard_wake:
            self._record(trace, "ignored", text, reason="no_wake_word", stt_ms=stt_ms,
                         audio_s=audio_s)
            return
        body = self.wake.remove_from(text) if self.wake.enabled else text
        if not body:
            self._spawn(self.speak(SAY_YES, trace))
            self._record(trace, "ignored", text, reason="wake_word_only", stt_ms=stt_ms,
                         audio_s=audio_s)
            return

        grammar_hit = match(body, self.cfg.grammar_max_words)
        if grammar_hit is None:  # only now is the server worth waiting for
            better = await self._maybe_escalate_stt(utterance, heard)
            if better is not None:
                if self._honour_stop(better, text, trace, stt_ms, total, audio_s):
                    return
                body = self.wake.remove_from(better) if self.wake.enabled else better
                grammar_hit = match(body, self.cfg.grammar_max_words)
        if grammar_hit is not None:
            if grammar_hit.act in (MOTION_ACTS | _POSTURE_ACTS | MOVE_ACTS | LOOK_ACTS) and \
                    self._too_old(utterance):
                self._record(trace, "ignored", text, reason="too_old", act=grammar_hit.act,
                             stt_ms=stt_ms, audio_s=audio_s)
                return
            self.wake.extend(self.clock())
            speech = self._act(grammar_hit.act, grammar_hit.say, body, trace)
            self.total_hist.record(total.ms())
            self._record_after(speech, trace, "grammar", text, act=grammar_hit.act,
                               say=grammar_hit.say, stt_ms=stt_ms, total_ms=total.ms(),
                               audio_s=audio_s)
            return

        watch = Stopwatch()
        fired: list[str] = []

        def early(act: str) -> None:
            """The moment the act is readable. It still has to name what the owner actually said."""
            if act != "stop" and (act not in MOTION_ACTS or self._too_old(utterance)):
                return
            if cross_check(RouterDecision(act, ""), body).act == act:
                fired.append(act)
                self._send_act(act, trace)

        try:
            decision = cross_check(await self.router.route(body, early), body)
        except Exception as exc:
            log.warning("router failed: %r", exc)
            self.failures += 1
            self._spawn(self.speak(SAY_THINK_FAILED, trace))
            self._record(trace, "failed", text, reason="router", stt_ms=stt_ms, audio_s=audio_s)
            return
        route_ms = watch.ms()
        self.route_hist.record(route_ms)
        self.wake.extend(self.clock())

        if decision.act in (MOTION_ACTS | MOVE_ACTS) and decision.act not in fired and \
                self._too_old(utterance):
            self._record(trace, "ignored", text, reason="too_old", act=decision.act, stt_ms=stt_ms,
                         route_ms=route_ms, audio_s=audio_s)
            return
        route: VoiceRoute = "llm"
        speech: asyncio.Task | None = None
        if decision.act == "none" and self._is_question(body) and self.answerers:
            route = "escalate"
            self._spawn_escalation(self._answer(body, trace))
        else:
            speech = self._act(decision.act, decision.say, body, trace,
                               already_sent=decision.act in fired)
        self.total_hist.record(total.ms())
        self._record_after(speech, trace, route, text, act=decision.act, say=decision.say,
                           stt_ms=stt_ms, route_ms=route_ms, total_ms=total.ms(), audio_s=audio_s)

    def _honour_stop(
        self, heard_text: str, record_text: str, trace: str, stt_ms: float, total: Stopwatch,
        audio_s: float,
    ) -> bool:
        """Stop words: no wake word, no confidence check, no model, and never too old."""
        hit = self.stop_words.match(heard_text)
        if hit is None:
            return False
        seq = (self.gw.estop if hit.emergency else self.gw.stop)(trace)
        for task in list(self._escalations):
            task.cancel()
        self.audio.cut()
        self.total_hist.record(total.ms())
        say = SAY_STOPPED if seq >= 0 else SAY_STOP_FAILED
        self._record(trace, "stop", record_text, act="estop" if hit.emergency else "stop", say=say,
                     reason="" if seq >= 0 else "broker_unreachable", stt_ms=stt_ms,
                     total_ms=total.ms(), audio_s=audio_s)
        self._spawn(self.speak(say, trace))
        return True

    def _acceptable(self, text: str, heard: Transcript) -> bool:
        s = self.cfg.stt
        return bool(text) and heard.no_speech_prob <= s.max_no_speech_prob \
            and heard.avg_logprob >= s.min_avg_logprob

    def _is_question(self, text: str) -> bool:
        return any(word in QUESTION_WORDS for word in tokens(text))

    async def _maybe_escalate_stt(self, utterance: Utterance, heard: Transcript) -> str | None:
        """A hard utterance goes to the bigger model. None means keep the local text."""
        if self.stt_escalate is None or heard.avg_logprob >= self.cfg.stt.escalate_below_logprob:
            return None
        try:
            better = await self.stt_escalate.transcribe(utterance.pcm16,
                                                        self.cfg.audio.sample_rate)
        except Exception as exc:
            log.info("stt escalation failed: %r", exc)
            return None
        return better.text.strip() or None

    # ------------------------------------------------------------------ doing and saying
    def _send_act(self, act: str, trace: str) -> None:
        if act == "stop":
            self.gw.stop(trace)
            return
        cmd = to_command(act, self.cfg.motion)
        if cmd is not None:
            self.gw.send(cmd, trace, qos=0 if act in MOTION_ACTS else 1)

    def _act(
        self, act: str, say: str, body: str, trace: str, already_sent: bool = False
    ) -> asyncio.Task | None:
        """Send the command at once and start the speech. Returns the speech task, if any."""
        if act == "look":
            self._spawn_escalation(self._look(body, trace))
            return None
        if not already_sent:
            self._send_act(act, trace)
        if act in (MOTION_ACTS | MOVE_ACTS):
            say = short_clause(say, self.cfg.motion.say_max_chars)
        return self._spawn(self.speak(say or SAY_DONE, trace))

    async def _look(self, question: str, trace: str) -> None:
        """Vision answers are spoken only. Nothing in this path can produce a command."""
        await self.speak(self.cfg.escalation.filler, trace)
        answer: str | None = None
        for service in self.vision:
            try:
                answer = await service.ask(question, trace)
                break
            except Exception as exc:
                log.warning("vision failed: %r", exc)
        await self.speak(answer or self.cfg.escalation.failure, trace)

    async def _answer(self, question: str, trace: str) -> None:
        """Server or cloud answers are spoken only."""
        await self.speak(self.cfg.escalation.filler, trace)
        answer: str | None = None
        for service in self.answerers:
            try:
                answer = await service.answer(question, trace)
                break
            except Exception as exc:
                log.warning("answer failed: %r", exc)
        await self.speak(answer or self.cfg.escalation.failure, trace)

    def can_speak_remote(self) -> bool:
        """A brain ask may speak only when no utterance is in flight and no audio is playing."""
        return (not self._speech_lock.locked() and not self.echo.playing(self.clock())
                and not self._tasks and not self._escalations and not self._short_queue
                and self._long_pending is None and self._stt_running == 0)

    def speak_remote(self, text: str, trace: str = "") -> bool:
        """Speak a brain request, or drop it. Never cuts over the owner's own turn."""
        if not self.can_speak_remote():
            return False
        self._spawn(self.speak(text, trace))
        return True

    async def speak(self, text: str, trace: str = "") -> float | None:
        clean = self.stop_words.strip_from(text)[:MAX_SPOKEN_CHARS] or SAY_DONE
        self.audio.cut()  # newest speech wins
        async with self._speech_lock:
            self.echo.start_playback()
            try:
                return await self._play(clean)
            except Exception as exc:
                log.warning("speech failed: %r", exc)
                self.failures += 1
                return None
            finally:
                self.echo.stop_playback(self.clock())

    async def _play(self, text: str) -> float | None:
        if text in self.canned:
            pcm, rate = self.canned[text]

            async def once() -> AsyncIterator[bytes]:
                yield pcm

            return await self.audio.play(once(), rate)
        try:
            return await self.audio.play(self.tts.synthesize(text), self.tts.sample_rate)
        except Exception as exc:
            if self.tts_fallback is None:
                raise
            log.warning("primary TTS failed, using fallback: %r", exc)
            return await self.audio.play(self.tts_fallback.synthesize(text),
                                         self.tts_fallback.sample_rate)

    def _record_after(self, speech: asyncio.Task | None, *args, **kwargs) -> None:
        """Write the turn once its speech has started, so the record holds time to first audio."""
        if speech is None:
            self._record(*args, **kwargs)
            return

        async def wait_then_record() -> None:
            first_s = None
            with contextlib.suppress(asyncio.CancelledError):
                first_s = await speech
            kwargs["tts_first_ms"] = None if first_s is None else first_s * 1000.0
            self._record(*args, **kwargs)

        self._spawn(wait_then_record())

    def _record(
        self, trace: str, route: VoiceRoute, transcript: str = "", act: str = "none", say: str = "",
        reason: str = "", stt_ms: float | None = None, route_ms: float | None = None,
        total_ms: float | None = None, audio_s: float | None = None,
        tts_first_ms: float | None = None,
    ) -> None:
        self.turns += 1
        turn = VoiceTurn(
            trace=trace, route=route, transcript=transcript[:200], act=act, say=say[:200],
            reason=reason, stt_ms=stt_ms, route_ms=route_ms, total_ms=total_ms,
            tts_first_ms=tts_first_ms, audio_ms=None if audio_s is None else audio_s * 1000.0,
        )
        log.info("turn", extra={"fields": turn.model_dump(exclude_none=True)})
        if self.publish_turn is not None:
            self.publish_turn(turn)

    async def prepare(self) -> None:
        """Before reporting ready: render the fixed phrases and load the router into memory."""
        e = self.cfg.escalation
        for text in {SAY_STOPPED, SAY_YES, SAY_DONE, SAY_THINK_FAILED, e.filler, e.failure,
                     *CANNED_SAY.values()}:
            try:
                pcm = b"".join([chunk async for chunk in self.tts.synthesize(text)])
                self.canned[text] = (pcm, self.tts.sample_rate)
            except Exception as exc:
                log.warning("could not pre-render %r: %r", text, exc)
        try:
            await self.router.route("مرحبا")
        except Exception as exc:
            log.warning("router warm-up failed: %r", exc)
        self.ready = True

    async def drain(self) -> None:
        """Wait for everything in flight. Used by tests and at shutdown."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
            await asyncio.sleep(0)  # finished tasks leave the set in a callback; let it run


__all__ = ["RouterDecision", "VoicePipeline"]
