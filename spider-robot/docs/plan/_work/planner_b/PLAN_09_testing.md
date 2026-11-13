# 9. Testing

## 9.1 Levels and what exists

| Level | Runs where | What it proves | Status |
|---|---|---|---|
| Unit | Mac, CI | Logic per module | 336 tests pass [V] |
| Contract | Mac, CI | Rolling-update rules; every client's topics against the real ACL file | In the 336 [V] |
| Simulator | Mac, CI | Brain, real gateway and simulated body in one process | In the 336 [V] |
| Broker smoke | Mac | `MqttLink` against a real broker process (amqtt, **not Mosquitto**) | Passed once [V] |
| Integration on Pi | Pi | Real Mosquitto, ACL, services | Not run |
| Bench B-series | Pi, server, stand | Replaces every [E] | Not run |
| Hardware in the loop | Robot on a stand, then floor | Real motion | Not run |
| Fault injection | Pi, server | FMEA responses | Not run |
| Soak | Whole system | 24 h stability | Not run |

## 9.2 Benches that replace estimates

Every bench saves a JSON or log file named in `PROGRESS` so the result stays with the repo.

| ID | Replaces | Method | Pass |
|---|---|---|---|
| **B1** | Q1, N1-N5, Core 0 budget | Robot on a stand, walking in place. (a) `cyclictest -m -p90 -a0 -i1000 -l3600000`. (b) `stress-ng --cpu 3 --taskset 1-3 --vm 1 --vm-bytes 800M` plus 1 utterance per 10 s, 1 h. (c) Read `loop_late_hist` at start and end. (d) Logic analyser on one SSC-32U channel for 60 s. Repeat at L0, then each rung needed | N1-N5 |
| B2 | H-2, sector coverage | 60 s static scene with `history_clouds` 1 and 3; per-sector hit rate; board at 0.5 m in every sector | No sector reads clear with a board present |
| B3 | Thermal | 30 min full voice load in the final enclosure | N31 |
| B4 | Power | All legs under load; `vcgencmd get_throttled` during wake and stall | No under-voltage bit |
| B5 | Reflexes | Board in the path at top speed; manual tilt | N6, N7 |
| B6 | Limp, SSC | Send `relax`, feel slack and read the scope for no pulses | Pulses stop |
| **B-V1** | Local STT, decides P1 | `spider-voice-bench` with local config, 200 utterances, Core 0 walking load running | Record p50, p95. If p95 over 2.5 s, set server first |
| **B-V2** | Server STT, router, TTS | Same corpus with server STT. Confirms `maxLength` is honoured, and prefix caching by comparing first and second calls | N16, N19, N20, N21, N22 |
| **B-V3** | Arabic quality | 200 utterances by the owner: 40 stop words, 100 commands, 60 free speech, at 1 m and 3 m | Stop recall ≥ 95% on the chosen STT; command accuracy ≥ 85%; zero false motion on free speech |
| B-V4 | Background, false triggers | 30 min TV or conversation; 10 min walking with no speech | False motion 0; false pre-stop ≤ 1 per minute walking. Otherwise raise `min_rms_dbfs` or aggressiveness, or limit pre-stop scope |
| B-V5 | N8 true timing | A click on the mic line and a logic probe on the SSC-32U TX line | N8 |
| B-S1 | Vision and RAM | 50 frames through `llama-vision`; `ask` over MQTT | N23, N32. Set `SB_VISION_TIMEOUT_S` to p95 plus 50% |
| B-S2 | Soak | 24 h with synthetic voice every 60 s | N28, N30, N33 |
| B-N1 | Q4 | `tc netem` on the server: 300 ms, 1 s, 5 s, 10% loss | Robot stops when it should; never moves on a late Move |
| B-N2 | N14 | 50 Telegram Stops, timed by video | N14 |
| B-F1 | N25 | Boot with Wi-Fi off and a wrong clock | Local voice works |
| B-F2 | R-6 | 20 hard power cuts | Boots every time |

## 9.3 Fault injection

| ID | Injection | Expected | Check |
|---|---|---|---|
| FI-1 | `kill -9` body while walking | Holds, then limp on restart | Log, motion |
| FI-2 | `kill -9` gateway while walking | Stop in ≤1.5 s, recovers | Log |
| FI-3 | `kill -STOP` voice during its Move | Stop in ≤1.75 s | `link_lost` |
| FI-4 | Gateway hang | As FI-2 | Log |
| FI-5 | `systemctl stop mosquitto` while walking | Stop in ≤1.5 s, reconnect ≤2 s | Log |
| FI-6 | Unplug server during remote walk | Stop in ≤1.75 s | Video |
| FI-7 | `tc netem` | As B-N1 | Log |
| FI-8 | Step the server clock ±10 s | Moves refused at most 30 s; no motion on a stale Move | `gw/status` |
| FI-9 | Unplug L2 | Refused with a spoken reason | Log |
| FI-10 | Bridge publishes clouds and no IMU | Refused | `limiter` |
| FI-11 | Unplug SSC-32U USB | Exits, restarts, alert | Log |
| FI-12 | Stop Ollama | Grammar works; router apology | Trace |
| FI-13 | Tilt past 55° on a stand | Limp, needs wake | Video |
| FI-14 | Replace client certificate with an expired one | Remote lost, local fine, alert | Log |
| FI-15 | Unplug camera, request a release | Release refused, E-stop stays | Telegram |
| FI-16 | `stress-ng --vm` to exhaust memory | Ollama dies first; body keeps ticking | `dmesg`, `loop_late_hist` |

## 9.4 Gates per milestone

| Milestone | Pass | Fail means |
|---|---|---|
| M0 Baseline | All package tests and ruff pass on the Pi and Mac. Hardware E-stop wired and proven | Stop |
| M1 Gateway, body, Pi broker | Automated tests; FI-2, FI-3, FI-5; B1 at L0 or a named rung; B5; B6; first walk at 0.03 m/s | Fix or climb the ladder |
| M2 Voice | Automated tests; B-V1, B-V2 (local parts), B-V3 stop recall on local STT, B-V4, B-V5 | Change STT order or thresholds |
| M3 Server | B-S1; B-V2 and B-V3 with server STT; FI-6; ask and vision answers spoken | Reduce models, or fall back to Ollama-free defaults |
| M4 Remote | ACL and firewall checks with `nmap` (N34); B-N1, B-N2; FI-8, FI-14, FI-15; 30-minute guarded remote session | Remote stays off |
| M5 Cloud escalation | Key-gated call answered; call failure spoken; privacy note accepted | Stay local |
| M6 Mapping | One real recording replayed through Point-LIO; AWS self-stop tested idle and at hard limit; budget alarm exists | AWS stays off |
| M7 Soak | B-S2, B-F1, B-F2 | Fix and repeat |

## 9.5 CI

`.github/workflows/spider-robot.yml`: per package, `uv run --frozen --all-extras --python 3.12 pytest -q` and `ruff check .`, plus `bash -n` on every shell script. **The workflow file has not been run**; it needs a push to GitHub, which this plan did not do.
