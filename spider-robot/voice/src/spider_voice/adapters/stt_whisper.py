"""faster-whisper (CTranslate2) on the Pi. Runs in worker threads; never blocks the event loop."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..config import WhisperLocalCfg
from ..interfaces import Transcript


class TranscribeTimeout(TimeoutError):
    """The caller gave up, but the thread is still using a worker until `running` is done."""

    def __init__(self, running: asyncio.Future) -> None:
        super().__init__("whisper timed out")
        self.running = running


class WhisperLocalSTT:
    def __init__(self, cfg: WhisperLocalCfg, model=None) -> None:
        self.cfg = cfg
        # Loaded here, once, before anyone speaks: the first Stop must not pay the load time.
        self._model = model if model is not None else self._create()
        self._pool = ThreadPoolExecutor(max_workers=cfg.workers, thread_name_prefix="stt")

    def _create(self):
        from faster_whisper import WhisperModel

        c = self.cfg
        return WhisperModel(c.model, device="cpu", compute_type=c.compute_type,
                            cpu_threads=c.cpu_threads, num_workers=c.workers)

    def _run(self, pcm16: bytes) -> Transcript:
        audio = np.frombuffer(pcm16, dtype="<i2").astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio, language=self.cfg.language, beam_size=1, vad_filter=False,
            condition_on_previous_text=False, without_timestamps=True,
            initial_prompt=self.cfg.prompt or None,
        )
        parts = list(segments)
        if not parts:
            return Transcript("", avg_logprob=-10.0, no_speech_prob=1.0)
        return Transcript(
            text=" ".join(s.text.strip() for s in parts).strip(),
            avg_logprob=sum(s.avg_logprob for s in parts) / len(parts),
            no_speech_prob=max(s.no_speech_prob for s in parts),
        )

    async def transcribe(self, pcm16: bytes, sample_rate: int) -> Transcript:
        if sample_rate != 16000:
            raise ValueError("whisper needs 16 kHz audio")
        loop = asyncio.get_running_loop()
        work = loop.run_in_executor(self._pool, self._run, pcm16)
        done, _ = await asyncio.wait({work}, timeout=self.cfg.timeout_s)
        if not done:
            raise TranscribeTimeout(work)
        return work.result()
