# 1. Requirements

Test IDs refer to the catalogue in `PLAN_09_testing.md`. Bench tests all need the real hardware and
have not been run.

## 1.1 Functional requirements

| ID | Requirement | Verified by |
|---|---|---|
| F-01 | Walk, turn, stand, sit, relax on command, with a tripod gait by default | Unit, RT2 |
| F-02 | Every motion command expires by itself | Unit `test_walk_forward_then_move_done`, RT2 |
| F-03 | Understand Arabic voice commands offline: Stop, walk, turn, stand, sit, look | Pipeline tests, V1, V2 |
| F-04 | Speak Arabic replies offline | Adapter tests, V3 |
| F-05 | A stop word needs no wake word, no confidence and no model | `test_stop_word_*` |
| F-06 | Motion by voice needs the wake word or a recent command | `test_background_speech_cannot_move_the_robot` |
| F-07 | Remote control from Telegram and the dashboard, through Tailscale | Brain tests, NET1 |
| F-08 | SSH fallback console works with the server down | `test_console.py`, NET3 |
| F-09 | Remote E-stop release needs a fresh frame and explicit confirmation | `test_remote_release_needs_*` |
| F-10 | Vision and cloud answers are spoken only and cannot cause motion | `test_vision_answer_is_spoken_*` |
| F-11 | Obstacle stop, tilt stop, fall detection, link watchdog, all on the robot | Body tests, RT3 |
| F-12 | LiDAR recording on request; mapping on the server or AWS on request | `test_recorder.py`, `test_jobs.py`, M7 gate |
| F-13 | STT, TTS, LLM and vision are selected by config | `registry.py`, `test_routing.py` |

## 1.2 Non-functional targets

### Latency (voice)

"End of speech" is the last voiced frame. Each stage is logged per utterance in `VoiceTurn`.

| ID | Stage | Target | Status | Measured by |
|---|---|---|---|---|
| L-01 | VAD end-of-speech hangover | 300 ms, configured | **[V]** config | V1 |
| L-02 | Whisper tiny on 3 cores, short utterance | p95 ≤ 2.5 s | **[E]** 1.0-2.5 s. No published Pi 4 figure found. faster-whisper's own source pads each window before encoding, so a short clip pays a large share of the full-window encoder cost | V1 replaces this |
| L-03 | Stop-word match | ≤ 1 ms | **[E]**, list is 12 words | Unit timing, V1 |
| L-04 | Grammar match | ≤ 1 ms | **[E]** | Unit timing, V1 |
| L-05 | LLM router, full reply | p95 ≤ 2.0 s | **[E]** LFM2.5-350M Q4 on Cortex-A72. Basis: size class only. No published Pi 4 figure | S1 replaces this |
| L-06 | TTS first audio, short phrase | p95 ≤ 700 ms | **[E]** Piper low voice. No reliable Pi 4 figure | V3 replaces this |
| L-07 | End of speech → motion starts, grammar path | p95 ≤ 3.0 s | **[E]** sum of L-01, L-02, L-04, L-10 | V4 |
| L-08 | End of speech → motion starts, LLM path | p95 ≤ 5.0 s | **[E]** | V4 |
| L-09 | End of speech → first spoken word, grammar path | p95 ≤ 3.7 s | **[E]** | V4 |

### Stop-to-motion-halt

Two moments are defined: **braking starts** when the body has accepted the Stop, and **halted** when
effective velocity reaches zero. Braking at 0.25 m/s² (`body/config/robot.example.yaml:86`) from
0.12 m/s takes 0.48 s and 2.9 cm **[V]** arithmetic from config; from voice speed 0.06 m/s, 0.24 s.

| ID | Path | Target to braking start | Status | Measured by |
|---|---|---|---|---|
| L-10 | Gateway receives Stop → body braking | p99 ≤ 40 ms | **[E]** includes up to one 20 ms tick and loopback MQTT (repo measured about 2 ms round trip at `infra/local/mosquitto-sim.conf:3`, on another broker setup) | RT4 |
| L-11 | Spoken Stop, end of speech → braking | **p95 ≤ 2.9 s; cannot be under 1 s on this hardware** | **[E]** L-01 + L-02 + L-03 + L-10 | V4 |
| L-12 | Telegram or dashboard Stop on LAN → braking | p95 ≤ 300 ms after the server receives it | **[E]** | NET1 |
| L-13 | Same, through a Tailscale relay | p95 ≤ 800 ms after the server receives it | **[E]** third-party relay latency up to about 450 ms **[S]** | NET2 |
| L-14 | LiDAR sees obstacle → braking | ≤ 300 ms worst case | **[E]** 180 ms revolution + 83 ms cloud + 20 ms tick, from L2 manual rates | RT3 |
| L-15 | Hardware E-stop press → servo power off | ≤ 20 ms | **[E]** typical relay release | HW2 with a scope |
| L-16 | Link or source lost → braking | ≤ 1.75 s, and the Move has already expired by 1.0 s for remote | **[V]** arithmetic from `policy.py` and the 10 Hz tick | Fault tests, NET2 |

### Control loop

| ID | Metric | Target | Measured by |
|---|---|---|---|
| R-01 | Tick start lateness p99.9, under full AI load | ≤ 5 ms | RT1 (`bench_jitter.sh`, `RobotState.loop_late_*`) |
| R-02 | Tick start lateness, maximum in 1 h | ≤ 18 ms (under one period) | RT1 |
| R-03 | Tick duration p99.9 | ≤ 6 ms | RT1 |
| R-04 | Ticks later than 40 ms | 0 per hour | RT1 |
| R-05 | Overruns | ≤ 1 per 10,000 ticks | RT1, `loop_overruns` |
| R-06 | `cyclictest` on core 0 under load, max | ≤ 2 ms | RT1 |

Why these limits: servos are commanded at 25 Hz with 40 ms interpolation
(`body/config/robot.example.yaml:53`), so a few milliseconds of jitter is mechanically invisible. The
limits exist to catch stalls.

### Availability per failure mode

Availability here means "what still works while this one thing is broken". Full table in
`PLAN_05_failure_analysis.md`.

| Failure | Stop | Local voice motion | Remote | Vision | Target recovery |
|---|---|---|---|---|---|
| Home server down | ✓ | ✓ | Telegram no; SSH yes | No | Automatic on return |
| Wi-Fi down | ✓ | ✓ | No | No | Automatic |
| Internet down | ✓ | ✓ | LAN and tailnet path only; Telegram no | Local yes, cloud no | Automatic |
| Gateway down | Body stops by watchdog in ≤ 1.5 s | No | No | No | Restart in ≤ 3 s |
| Broker down | Body stops by watchdog in ≤ 1.5 s | No | No | No | Restart in ≤ 5 s |
| Voice service down | Other sources work | No | ✓ | ✓ | Restart in ≤ 5 s |

Voice-loop service availability: ≥ 99% over a 24 h soak (S2).

### Resource ceilings

Enforced by `MemoryMax=` in the unit files. Budgets and estimates are in `PLAN_04_budgets.md`.

| Node | Item | Ceiling |
|---|---|---|
| Pi | Core 0 utilisation | ≤ 40% average, measured in RT1 |
| Pi | Total RAM in use, all services | ≤ 2.5 GB of 4 GB |
| Pi | Swap | None; a swap of the control process is a stall |
| Pi | CPU temperature under full load | ≤ 80 °C (throttling begins near there) |
| Server | RAM used by all Spider services | ≤ 5.0 GB, within about 5.7 GB free in daily use **[S: brief]** |

### Other

| ID | Requirement | Target |
|---|---|---|
| N-01 | Time from power-on to voice ready | ≤ 90 s **[E]**, V5 |
| N-02 | Worst-case travel after total link loss during remote control | ≤ 6 cm **[V]** arithmetic: 0.05 m/s × 1.0 s, plus 0.5 cm of braking |
| N-03 | Worst-case travel for one voice command | ≤ 18 cm **[V]** arithmetic: caps of 0.08 m/s × 2.0 s, plus 1.3 cm of braking. The default command is 9 cm |
| N-04 | Pi operates with no network indefinitely | M5 gate, V5 |
| N-05 | No secret in the repository | CI secret scan, `PLAN_10_delivery.md` |
