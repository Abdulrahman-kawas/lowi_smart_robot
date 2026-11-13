# 9. Testing

Software tests ran on the Mac with simulated hardware and in-memory links (`VALIDATION.md`). Every test
in sections 9.2 onward needs real hardware and **has not been run**.

## 9.1 Automated tests in the repository

| Level | What | Where |
|---|---|---|
| Unit | Protocol, histograms, IK, gait, safety, LiDAR merge, stop words, grammar, segmenter, echo gate, router parsing, policy | Each package's `tests/` |
| Contract | v2 source accepted by v3 gateway; v3 fields round trip; unknown version refused; ACL file (static) | `common/tests`, `gateway/tests` |
| Adapter | Whisper, Piper, Ollama, OpenAI-compatible, server STT, with fakes for the engine or HTTP | `voice/tests/test_routing.py` |
| Simulator, end to end | Voice pipeline through the real gateway to the real body code on a simulated robot; gateway-to-body; brain-to-body | `voice/tests/test_pipeline.py`, `gateway/tests/test_gateway.py`, `brain/tests/test_brain.py` |
| Fault injection, in software | Lost owner, late messages, clock skew and steps, garbage, truncated recordings, failed engines | Throughout |
| Regression, safety | One test per defect D1-D18 where software can show it | `body/tests/test_safety_fixes.py` and others |

Run: `cd <package> && uv run --all-extras pytest -q`, for each of common, body, gateway, voice, brain.

## 9.2 Real-time bench tests

| ID | Test | Method | Pass |
|---|---|---|---|
| RT1 | Control timing under load | `infra/pi/bench_jitter.sh 3600`, robot on stand; also `cyclictest -a 0 -p 80 -m -D 1h` | R-01 to R-06; `rt_ok` true |
| RT2 | Gait on a stand | 30 min walking in the air | No overruns beyond R-05; smooth motion by eye and video |
| RT3 | Reflex on the floor | Cardboard obstacle at 1 m, 20 runs, at 0.12 m/s; measure the stopping gap with a ruler | Stops with at least 10 cm remaining, every run |
| RT4 | Stop latency through the real broker | Scope or high-speed video on a Stop at the gateway to the first slowdown | L-10 |

## 9.3 Voice bench tests

| ID | Test | Method | Pass |
|---|---|---|---|
| V1 | STT latency | 100 owner clips, 0.5-4 s; log `stt_ms` | Replaces L-02; p95 ≤ 2.5 s |
| V2 | Word accuracy and false triggers | 200 clips of 10 commands, quiet and with gait noise; then 30 min of TV audio | Stop recall ≥ 95% quiet, ≥ 85% noisy; **zero false motion** on TV audio; note the false-stop rate |
| V3 | TTS and self-hearing | First-audio time on 20 phrases; 30 min of robot speech with the microphone live | Replaces L-06; robot never acts on its own voice |
| V4 | End-to-end and speech onset | High-speed video: speech end to first leg movement. Then enable `stop_on_speech_onset` and walk in a quiet room | L-07, L-11. Onset feature stays off unless false stops are under one per 10 min of walking |
| V5 | No network at all | Disconnect everything; power on; run commands | Voice ready ≤ 90 s; all voice functions work |
| V6 | Vision backends | One image through `llama-server`, then through Ollama. Time on the i7-8700 | Vision works and timeout is set from the measurement. Records whether Ollama loads the projector |
| S1 | Router speed and Arabic quality | 100 Arabic prompts through LFM2.5-350M on the Pi. Count JSON validity, correct `act`, truncations | ≥ 98% valid JSON; 0 truncated at `num_predict` 64; p95 replaces L-05 |
| S2 | Soak | 24 h idle plus an utterance a minute; check memory | No restart; memory flat within 10%; RT1's limits still met |

## 9.4 Network tests

| ID | Test | Method | Pass |
|---|---|---|---|
| NET1 | Direct LAN path | `tailscale ping`; `spider-brain ping --n 200`; Telegram Stop | Direct connection; L-12 |
| NET2 | Bad network | `tc qdisc add dev tailscale0 root netem delay 300ms 100ms loss 5%`, then pull Wi-Fi during a remote walk | L-13; motion ends by itself within 1.75 s; never moves on stale commands |
| NET3 | Server off | Stop the server during use | Voice unaffected; console works over SSH |
| NET4 | Internet off | Block WAN | Local and server functions keep working |
| NET5 | Broker ACL | Attempt each forbidden publish with each certificate using `mosquitto_pub` | Every one refused, including anyone but the gateway writing to `cmd` |

## 9.5 Fault injection on the Pi

All with the robot on the stand, walking in the air, unless noted.

| ID | Inject | Pass |
|---|---|---|
| FI1 | `kill -9` spider-body | Servos hold; restart within 5 s; relaxes; does not move on its own |
| FI2 | `kill -STOP` spider-body | systemd kills and restarts within 2 s |
| FI3 | `kill -9` lidar_bridge | No motion within 0.5 s of data loss |
| FI4 | `kill -9` spider-gateway | Robot stops within 1.5 s; offline status visible |
| FI5 | `systemctl stop mosquitto` | Robot stops within 1.5 s; everything reconnects after restart |
| FI6 | `kill -9` spider-voice; unplug the microphone | Other sources unaffected; health shows down |
| FI7 | `kill -STOP` ollama | Router timeout; spoken failure; no motion |
| FI8 | Stop spider-brain during a remote walk | Robot stops by itself |
| FI9 | Pull the USB cable to the SSC-32U | Exits cleanly after 0.5 s; no crash loop damage; recovers on replug |
| FI10 | `date -s` forward 1 h on the server | Remote recovers in ≤ 3 s; no motion on stale commands |

## 9.6 Hardware bench tests

| ID | Test | Method | Pass |
|---|---|---|---|
| HW1 | L2 bring-up | Provision the work mode; confirm IMU at about 100 Hz; check clouds, sweeps and sector map against known objects; **confirm the FOV finding with a low object** | Map matches reality; IMU reports; mount decided |
| HW2 | Power cut and `P0` | Press the switch with a scope on the servo rail. Separately send `P0` and feel the torque | L-15; records whether RDS3218 goes limp without pulses |
| HW3 | Hardware watchdog | Stop the toggling; scope the relay | Drops within 200 ms; re-arms safely |
| HW4 | Current | Clamp meter while walking and at stall; check the fuse and low-voltage alarm | Measured figures chosen for relay and fuse |
| HW5 | Thermal and power | 30 min at full AI load; then undervolt the supply | Below 80 °C with the fan; `spider-sysmon` reports throttling and undervoltage |

## 9.7 Gates

Each milestone's pass or fail gate is in `PLAN_13_roadmap.md`. A failure stops progress: no later
milestone starts until the gate passes or the plan is changed in writing.
