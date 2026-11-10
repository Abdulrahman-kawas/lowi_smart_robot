# 4. Budgets

Measured figures come from the Apple M2 dev machine (`VALIDATION.md` section 4), using the repo's own
code. The Pi figures multiply them by **×8**: an assumption for pure-Python work on a 1.5 GHz
Cortex-A72 **[E]**. RT1 replaces every Pi figure with a measurement.

## 4.1 Pi: Core 0

| Work | Rate | M2 cost, p50 **[V]** | Pi estimate per event **[E]** | Share of core **[E]** |
|---|---|---|---|---|
| `Robot.tick` while walking | 50 Hz | 29 µs (p99 196 µs) | 0.23 ms (p99 1.6 ms) | 1.2% |
| SSC-32U write, 166 bytes | 25 Hz | not measured | 0.2 ms | 0.5% |
| LiDAR cloud to sector map, 2,667 points, with the new merge | 12 Hz | 246 µs (p99 657 µs) | 2.0 ms (p99 5.3 ms) | 2.4% |
| IMU message handling | 100 Hz | 0.7 µs | under 0.01 ms | under 0.1% |
| ZeroMQ wake-up through asyncio | 112 Hz | not measured | 0.15 ms **[A]** | 1.7% |
| State JSON | 4 Hz | 5.9 µs | 0.05 ms | under 0.1% |
| Command parse and handling | ≤ 10 Hz | 1.1 µs parse, 3.4 µs event | 0.05 ms | under 0.1% |
| MQTT thread (paho, TLS) | low | not measured | n/a | 1% **[A]** |
| `spider-body` subtotal | | | | **about 7%** |
| `lidar_bridge`: 64,000 points/s, UDP parse | continuous | not measured | n/a | **5-10% [A]** |
| Residual kernel work: timer tick, RCU, unmovable IRQs | | | | 2-5% **[A]** |
| **Core 0 total** | | | | **about 15-25%, ceiling 40%** |

Headroom exists to absorb bursts. RT1 measures the actual total.

## 4.2 Pi: Cores 1-3

Whisper, the router and Piper run in sequence for one utterance, so their peaks mostly do not stack.

| Process | Idle | During an utterance | Notes **[E]** |
|---|---|---|---|
| `spider-voice` VAD and glue | 3% of one core | 3% | |
| Whisper tiny int8 | 0 | 3 cores for 1-2.5 s | |
| Ollama + LFM2.5-350M | 0 | 3 cores for 1-2 s | keep-alive, no reload |
| Piper | 0 | about 1 core for 0.3-0.7 s | |
| `spider-gateway` | 1% | 1% | |
| Mosquitto | 1% | 1% | |
| `spider-camera` | 0 | 1 core for about 50 ms per frame | |
| `spider-recorder` (during a job) | 0 | about 10% of one core | |
| **Peak** | | **about 3 cores for about 3-5 s per utterance** | |

Under sustained speech the Pi will be fully busy on cores 1-3, which is why the thermal limit matters.
A heatsink and fan are required. Without one, assume throttling.

## 4.3 Pi: RAM

Ceilings are enforced with `MemoryMax=`. Sizes are **[E]**, except where marked.

| Process | Estimate | Ceiling | Basis |
|---|---|---|---|
| OS and system services | 300 MB | none | Pi OS Lite |
| `spider-body` with locked memory | 150 MB | 400 MB | Python, numpy, pyzmq, paho; OpenCV no longer loaded **[V]** by test |
| `lidar_bridge` | 20 MB | 64 MB | |
| Mosquitto | 8 MB | system default | |
| `spider-gateway` | 45 MB | 128 MB | Python, pydantic, paho |
| `spider-camera` (OpenCV) | 90 MB | 256 MB | |
| `spider-recorder` | 45 MB | 200 MB | |
| `spider-voice`: Whisper tiny int8, Piper, ONNX Runtime, app | 500 MB | 900 MB | Tiny weights about 75 MB; voice file 63.2 MB **[S]** |
| Ollama + LFM2.5-350M Q4_K_M | 450 MB | 900 MB | File 229 MB **[S]**; "under 1 GB" per Liquid **[S]** |
| **Sum** | **about 1.6 GB** | | |
| Free for page cache | **about 2.4 GB** | | Ceiling on the sum: 2.5 GB |

## 4.4 Home server

i7-8700, 6C/12T, 15 GB RAM, about 5.7 GB free in daily use **[S: brief]**. Sizes **[E]**.

| Service | CPU | RAM | Ceiling |
|---|---|---|---|
| `spider-brain` | under 5% average | 300 MB | 1 GB, `CPUQuota=200%` |
| `llama-server` LFM2.5-VL-1.6B Q4_0, with projector | 6 threads, seconds per image | 1.6 GB | 3 GB |
| `llama-server` LFM2.5-1.2B Q4_K_M | 6 threads, per request | 1.2 GB | 3 GB |
| `spider-stt` Whisper small int8 | 4 threads, per request | 600 MB | 1.5 GB |
| **Sum** | | **about 3.7 GB** | |
| Point-LIO in a container, on demand | 4-8 threads | 2-4 GB | Stop vision first; it competes for CPU and RAM |

This fits, tightly. Swap is near full in daily use **[S: brief]**, so the architecture document's target
of about 8 GB free before loading models should be met by closing desktop apps. If it is not, drop the
1.2B model first, and run planner fallback in the cloud.

**With a later RTX 3060 12 GB:** VL and 1.2B move to the GPU, and vision falls to well under a second
per image. Changes needed: a build flag on `llama-server` and `-ngl 99` in the two unit files. Nothing
else.

## 4.5 Bandwidth

| Link | Traffic | Rate |
|---|---|---|
| Tailscale, Pi ↔ server, normal | state 4 Hz × ~2 KB, heartbeats, events | about 10 KB/s **[E]** |
| Tailscale, one camera frame | ≤ 120 KB | on demand |
| Tailscale, vision request, base64 | ≤ 160 KB | on demand |
| Tailscale, copy of a recording | 1.5 MB/s of recording | as fast as the link allows, off-line from the robot |
| Ethernet, L2 → Pi | 64,000 points/s plus IMU | about 1.5-3 MB/s **[E]** |
| USB serial, Pi → SSC-32U | 4.2 KB/s **[V]** of the 11.5 KB/s at 115200 baud | |
| AWS upload per 10 min recording | about 900 MB | on demand |

## 4.6 Latency budgets

Every line is **[E]** until the named test runs.

### Grammar command: end of speech to motion start, 2.9 s budget

| Stage | Budget | Test |
|---|---|---|
| VAD hangover | 300 ms | V1 |
| Whisper tiny | 2,500 ms | V1 |
| Stop, wake, grammar | 2 ms | V1 |
| Publish → broker → gateway → broker → body | 15 ms | RT4 |
| Wait for the next tick | 20 ms | RT1 |
| Ramp visible | 60 ms | V4 |
| **Total** | **2,897 ms** | V4 |

### LLM command: 4.9 s budget

As above, plus router 2,000 ms: **4,897 ms**.

### Spoken Stop to braking, p95: 2.84 s

300 + 2,500 + 1 + 15 + 20 = **2,836 ms**. This is why L-11 says 2.9 s.

### First word: grammar path, 3.5 s budget

300 + 2,500 + 2 + (TTS first audio 700) = **3,502 ms**. L-09's 3.7 s includes 200 ms of audio device
start-up **[A]**.

### Reflex: LiDAR to braking, 283 ms

Sweep 180 ms, cloud 83 ms, tick 20 ms. At 0.12 m/s that is 3.4 cm, plus 2.9 cm of braking, so 6.3 cm
of a 15 cm stop distance **[V]** arithmetic. Config validation now uses these numbers.
