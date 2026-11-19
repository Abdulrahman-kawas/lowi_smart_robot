"""Voice in and out, with the same stack as the JobHunt repo's orchestrator.py.

  hear:  voice note (OGG/Opus, MP3, M4A, WAV) -> Gemini (gemini_text_model, then
         gemini_fallback_model) -> transcript text
  speak: text -> Gemini TTS (gemini_tts_model, voice tts_voice) -> 24 kHz PCM -> ffmpeg -> OGG/Opus
         fallback: gTTS (Arabic when the text has Arabic letters) -> MP3 -> ffmpeg -> OGG/Opus

ffmpeg runs with a fixed argv (repo rule: no shell). Every failure degrades to "text only".
"""

from __future__ import annotations

import asyncio
import io
import logging
import random
import re
import shutil
import subprocess
import wave

from .config import Settings

log = logging.getLogger(__name__)

TRANSIENT = ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "overloaded", "high demand")
TRANSCRIBE_PROMPT = (
    "Transcribe exactly what the speaker says, in the language they speak (keep Arabic dialect "
    "words as spoken). Return only the transcript, with no comments. If there is no speech, "
    "return an empty string."
)
MAX_AUDIO_BYTES = 10 * 1024 * 1024


def _transient(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or any(m in str(exc) for m in TRANSIENT)


class VoiceService:
    def __init__(self, settings: Settings, client=None, ffmpeg: str | None = None) -> None:
        self.settings = settings
        self._client = client
        self.ffmpeg = ffmpeg if ffmpeg is not None else (shutil.which("ffmpeg") or "")

    @property
    def available(self) -> bool:
        return bool(self._client or self.settings.gemini_api_key)

    def _gemini(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            # v1beta: with google-genai 3.0.0 the default API version rejects speech_config
            # ("Unknown name speechConfig", HTTP 400), so every Gemini TTS call failed.
            self._client = genai.Client(api_key=self.settings.gemini_api_key or None,
                                        http_options=types.HttpOptions(api_version="v1beta"))
        return self._client

    # ------------------------------------------------------------------ hear
    async def transcribe(self, audio: bytes, mime_type: str = "audio/ogg") -> str:
        if len(audio) > MAX_AUDIO_BYTES:
            raise ValueError("voice note is larger than 10 MB")
        from google.genai import types

        s = self.settings
        models = [s.gemini_text_model]
        if s.gemini_fallback_model and s.gemini_fallback_model != s.gemini_text_model:
            models.append(s.gemini_fallback_model)
        contents = [types.Part.from_bytes(data=audio, mime_type=mime_type), TRANSCRIBE_PROMPT]
        last: Exception | None = None
        for model in models:  # primary with short backoff, then the fallback model
            for attempt in range(3):
                try:
                    resp = await asyncio.wait_for(
                        self._gemini().aio.models.generate_content(model=model, contents=contents),
                        timeout=90,
                    )
                    return (resp.text or "").strip()
                except Exception as exc:
                    last = exc
                    if not _transient(exc):
                        break
                    await asyncio.sleep(2**attempt + random.random())
        raise RuntimeError(f"transcription failed: {last}")

    # ------------------------------------------------------------------ speak
    def _ffmpeg_to_ogg(self, data: bytes, input_args: list[str]) -> bytes:
        out = subprocess.run(
            [self.ffmpeg, "-loglevel", "error", *input_args, "-i", "pipe:0",
             "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", "pipe:1"],
            input=data, capture_output=True, check=True, timeout=60,
        )
        return out.stdout

    def _speak_sync(self, text: str) -> tuple[bytes, str] | None:
        s = self.settings
        if self.ffmpeg and self.available:
            try:
                from google.genai import types

                resp = self._gemini().models.generate_content(
                    model=s.gemini_tts_model,
                    contents=f"Say naturally, warmly, and conversationally: {text}",
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=s.tts_voice)
                            )
                        ),
                    ),
                )
                pcm = resp.candidates[0].content.parts[0].inline_data.data
                return self._ffmpeg_to_ogg(pcm, ["-f", "s16le", "-ar", "24000", "-ac", "1"]), "ogg"
            except Exception as exc:
                log.warning("Gemini TTS failed (%s); trying gTTS", exc)
        try:
            from gtts import gTTS

            lang = "ar" if re.search(r"[؀-ۿ]", text) else s.voice_lang
            buf = io.BytesIO()
            gTTS(text=text, lang=lang).write_to_fp(buf)
            mp3 = buf.getvalue()
            if self.ffmpeg:
                return self._ffmpeg_to_ogg(mp3, []), "ogg"
            return mp3, "mp3"
        except Exception as exc:  # gTTS is an unofficial endpoint: text only then
            log.warning("TTS failed, text only: %s", exc)
            return None

    def _speak_wav_sync(self, text: str, voice_name: str) -> bytes:
        from google.genai import types

        resp = self._gemini().models.generate_content(
            model=self.settings.gemini_tts_model,
            contents=f"Say naturally, warmly, and conversationally: {text}",
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name))),
            ),
        )
        pcm = resp.candidates[0].content.parts[0].inline_data.data  # 24 kHz, mono, 16-bit
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24_000)
            out.writeframes(pcm)
        return buf.getvalue()

    async def speak_wav(self, text: str, voice_name: str, timeout_s: float = 25.0) -> bytes | None:
        """Gemini TTS as a WAV the phone can play (no ffmpeg). None when it fails or times out."""
        text = text.strip()
        if not text or not self.available:
            return None
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._speak_wav_sync, text[:1500], voice_name), timeout_s)
        except Exception as exc:
            log.warning("Gemini TTS for the app failed: %r", exc)
            return None

    async def speak(self, text: str) -> tuple[bytes, str] | None:
        """(audio bytes, "ogg" | "mp3") or None when no voice could be made."""
        text = text.strip()
        if not text:
            return None
        return await asyncio.to_thread(self._speak_sync, text[:1500])
