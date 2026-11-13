"""Bench harness: replaces the plan's voice estimates with numbers measured on the real Pi.

  spider-voice-bench --config /etc/spider/voice.yaml --manifest corpus.jsonl --out report.json

Each manifest line: {"wav": "a.wav", "text": "...", "act": "forward"}, 16 kHz mono 16-bit.
The robot does not move: nothing here connects to the broker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import wave
from pathlib import Path

from . import registry
from .config import VoiceConfig, load_config
from .grammar import match
from .stopwords import StopWords
from .text import tokens


def word_errors(ref: list[str], hyp: list[str]) -> int:
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[-1]


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p * len(ordered)))] if ordered else 0.0


def summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "p50": round(percentile(values, 0.5), 1),
            "p95": round(percentile(values, 0.95), 1), "max": round(max(values), 1),
            "mean": round(statistics.mean(values), 1)}


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError(f"{path}: must be 16 kHz mono 16-bit")
        return w.readframes(w.getnframes())


def _timestamper(seen: list[float], clock):
    return lambda _act: seen.append(clock())


async def run_bench(cfg: VoiceConfig, manifest: Path) -> dict:
    stt = registry.build_stt(cfg)
    router = registry.build_router(cfg)
    tts = registry.build_tts(cfg)
    stops = StopWords(cfg.stop_words, cfg.emergency_words)
    stt_ms, router_ms, first_act_ms, tts_ms = [], [], [], []
    words, errors, correct, total, stop_hits, stop_total = 0, 0, 0, 0, 0, 0
    clock = time.perf_counter
    base = manifest.parent
    for line in manifest.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        started = clock()
        heard = await stt.transcribe(read_pcm(base / item["wav"]), 16000)
        stt_ms.append((clock() - started) * 1000)
        ref, hyp = tokens(item["text"]), tokens(heard.text)
        words += len(ref)
        errors += word_errors(ref, hyp)
        expected = item.get("act")
        stopped = stops.match(heard.text) is not None
        if expected == "stop":
            stop_total += 1
            stop_hits += stopped
        hit = match(heard.text, cfg.grammar_max_words)
        act = "stop" if stopped else hit.act if hit is not None else None
        if act is None:
            started = clock()
            seen: list[float] = []
            decision = await router.route(heard.text, _timestamper(seen, clock))
            router_ms.append((clock() - started) * 1000)
            if seen:
                first_act_ms.append((seen[0] - started) * 1000)
            act = decision.act
        if expected is not None:
            total += 1
            correct += act == expected
    for text in (cfg.escalation.filler, "الطريق قدامي مسكر، لازم نلاقي طريق تاني"):
        started = clock()
        async for _chunk in tts.synthesize(text):
            break
        tts_ms.append((clock() - started) * 1000)
    return {
        "stt_ms": summary(stt_ms), "router_ms": summary(router_ms),
        "router_first_act_ms": summary(first_act_ms), "tts_first_audio_ms": summary(tts_ms),
        "word_error_rate": round(errors / words, 3) if words else None,
        "act_accuracy": round(correct / total, 3) if total else None,
        "stop_word_recall": round(stop_hits / stop_total, 3) if stop_total else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spider-voice-bench")
    parser.add_argument("--config", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", default="voice-bench.json")
    args = parser.parse_args(argv)
    report = asyncio.run(run_bench(load_config(args.config), Path(args.manifest)))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
