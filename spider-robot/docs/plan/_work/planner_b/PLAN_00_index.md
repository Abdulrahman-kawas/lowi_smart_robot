# Planner B plan: index, findings, open questions

Planner B: distributed systems and edge ML. Optimised for interface quality, operability, and fast delivery by one developer. Date of evidence: 2026-11-09 to 2026-11-10.

| Part | File |
|---|---|
| 1 Requirements | `PLAN_01_requirements.md` |
| 2 Architecture | `PLAN_02_architecture.md` |
| 3 Contracts | `PLAN_03_contracts.md` |
| 4 Budgets | `PLAN_04_budgets.md` |
| 5 Failure analysis (FMEA) | `PLAN_05_failure.md` |
| 6 Physical safety | `PLAN_06_safety.md` |
| 7 Security (STRIDE) | `PLAN_07_security.md` |
| 8 Observability | `PLAN_08_observability.md` |
| 9 Testing | `PLAN_09_testing.md` |
| 10 Delivery and runbooks | `PLAN_10_delivery.md` |
| 11 Cost | `PLAN_11_cost.md` |
| 12 ADRs | `PLAN_12_adrs.md` |
| 13 Roadmap | `PLAN_13_roadmap.md` |
| File map | `FILE_MAP.md` |
| Code | `code.patch` |
| Commands run and real output | `VALIDATION.md` |

## How to read the claims

Every number carries one of these labels.

| Label | Meaning |
|---|---|
| **[V]** | Verified: read in this repo (`file:line`), run here (see `VALIDATION.md`), or stated by a cited primary source |
| **[E]** | Estimated: reasoned from a stated basis. Each one names the bench test that replaces it |
| **[A]** | Assumed: no evidence either way. Named so it can be checked |

`file:line` citations refer to the working tree as it stood before this plan (scratch baseline commit `773c522`, identical to the owner's uncommitted tree). Nothing here has run on the real Pi, a real Mosquitto broker, the real server, or the robot.

## The plan in one page

**The defining finding is about speech recognition.** Published Pi 4 measurements put Whisper `tiny` at roughly 3-8 s per utterance, because Whisper always encodes a padded 30 s window. So "fast response" cannot come from local STT on this hardware, and the plan is built around that fact:

1. **Speech onset stops a moving robot in about 0.13 s before any model runs.** This is the safety path, and it works with no network.
2. **A deterministic Arabic grammar handles common commands** with no LLM.
3. **STT runs on the home server when reachable** (bench-decided), with local `tiny` as the offline fallback.
4. **The LLM router's `act` is read from the stream** before the reply finishes.

**Defects found in the existing code, each fixed in `code.patch` with a test:**

| # | Defect | Evidence | Severity |
|---|---|---|---|
| D1 | A voice Stop does not end a planner or remote walk. The next 0.5 s renewal restarts the robot, and the walker is never told | `gateway.py:97-103,107-112,113-116`; `robot_client.py:266-271`. Reproduced on the baseline: body saw `['move','stop','move']` and the planner received no event ([V], `VALIDATION.md` §2) | Blocking |
| D2 | Servo group moves slip. With 0.2 ms of tick jitter, 48% of send gaps exceed 45 ms and the mean is 49.7 ms against 40 ms, while `T40` glides end after 40 ms, so servos rest between moves | `servos.py:194`; simulated on the baseline ([V]) | High: gait quality |
| D3 | About 500 IMU messages/s wake the control loop's event loop. Measured 256 µs per message on an M2; at 6-10x slower ([A]) that is 77-128% of Core 0 ([E], bench B1) | `lidar_bridge.cpp:105-114`; `lidar.py:146-161`; L2 manual: 500 Hz report rate | High |
| D4 | Camera capture and JPEG encoding run on Core 0, against Decision 3. `to_thread` inherits the process affinity | `robot.py:225-231`; `camera.py:63-72` | High |
| D5 | `loop_max_ms` measures tick duration only. A wake-up 19 ms late is invisible, so the metric cannot prove the loop is healthy | `main.py:67,81,86-92` | High: blinds the main open question |
| D6 | Remote E-stop release has no frame or confirmation, against Decision 8 | `telegram.py:202-204`; `server.py:93-94`; `gateway.py:104-106` | Blocking |
| D7 | After a crash and restart while standing, state says relaxed but servos still hold the pose. The next `stand` drives them to the sit pose at full speed | `robot.py:80,200-204`; `SscServoBank` sends nothing at startup; SSC-32U guide p.25 | High: physical |
| D8 | The brain has one source, so planner motion and the owner's Telegram commands share one priority, against Decision 5 | brain `config.py:28`; `service.py:82` | High |
| D9 | The gateway compares timestamps from different machines and forwards the sender's `ts`, so server clock skew reaches the body's age check | `gateway.py:110,128,137`; `robot.py:122-126` | Medium |
| D10 | The E-stop cuts nothing electrical: it freezes the gait and servos keep full torque | `robot.py:132-138` | Blocking before unattended use |

**Top decisions:** the gateway is the enforcement point for every human-safety rule. MQTT is the only Pi-server channel, including STT and questions, so the server opens no model ports. Answers come back in a message type that has no action field. A loopback password listener keeps the robot working with no clock, no certificates and no network.

## Answers to the open questions

### Q1. Is the Python/asyncio 50 Hz loop on Core 0 good enough?

**Probably yes after the fixes; not proven until bench B1 passes.**

- The requirement is soft. The SSC-32U interpolates each group move over 40 ms ([V] `servos.py:195`), and at 0.12 m/s the robot travels 2.4 mm per tick. A late tick costs smoothness, not stability.
- Python's own cost is small: 60 µs mean, 199 µs p99 per walking tick on an M2 ([V]), so an estimated 0.4-0.6 ms mean and 1.2-2 ms p99 on a Pi 4 ([E]) against a 20 ms budget. The risks are event-loop load (D3) and interference.
- **Interference that pinning cannot remove:** the A72 cores share one L2 cache and one memory bus. Whisper or the LLM at full load will slow Core 0 even when nothing else runs on it. Only measurement can size this.
- **Proof is bench B1** (`PLAN_09_testing.md`): `cyclictest` for the kernel floor, the new `loop_late_hist`, and a logic analyser on the SSC-32U pulse output, under the full AI load.

| Rung | Change | Cost | Move up when |
|---|---|---|---|
| L0 (default) | `CPUAffinity=0`, everything else on 1-3, `irqaffinity=1-3`, `gc.freeze`, GIL switch 1 ms, IMU at 50 Hz | Shipped | - |
| L1 | `realtime.fifo_priority: 50` plus `mlock` | Config only | L0 fails the B1 gate |
| L2 | `isolcpus=0 nohz_full=0` | Boot parameter | L1 fails |
| L3 | PREEMPT_RT kernel, or move IK and gait to C++ | Days | L2 fails |

`isolcpus` is not needed first: on this box the competing user-space load is already kept off Core 0 by affinity, so the remaining noise is IRQs, which `irqaffinity` handles. `SCHED_FIFO` is a config switch because a runaway FIFO task can starve the core; `LimitRTTIME` guards it. Core 0 can be `nohz_full` on current kernels ([V] kernel commit 08ae95f4fd3b), so L2 stays available.

Gate: over 1 hour with full voice load, `loop_late` p99.9 ≤ 10 ms, no tick gap above 60 ms, `loop_overruns` growth ≤ 1 per 10 minutes.

### Q2. Real end-to-end voice latency and Arabic quality on a Pi 4?

**Local Whisper `tiny` cannot deliver a fast voice loop on a Pi 4. The best achievable is below.** These are estimates; bench B-V1 and B-V2 replace them with real numbers.

| Path | End of speech to command sent | Label |
|---|---|---|
| Speech onset pre-stop | 0.10-0.14 s after speech starts | [E], from `start_ms: 100` [V] |
| Stop word, server STT | 1.3-2.4 s | [E] |
| Grammar, server STT | 1.3-2.4 s | [E] |
| Grammar, offline with local `tiny` | 3.3-8.3 s | [E] |
| Router, server STT, act read early | 1.9-3.6 s | [E] |
| Router, offline | 3.9-9.5 s | [E] |

Basis for STT: 35 s for a 100 s clip with `tiny` on a Pi 4 ([MaibornWolff](https://www.maibornwolff.de/en/know-how/openai-whisper-raspberry-pi/)), about 9 s per 30 s window; whisper.cpp `tiny` 4-thread encode about 10-14 s ([issue #89](https://github.com/ggml-org/whisper.cpp/issues/89), older builds); `tiny_int8` 5-6 s from one Home Assistant user. faster-whisper pads each window to a fixed length before encoding ([V] `transcribe.py`), so a 1 s command costs nearly the same as 30 s of speech.

Router basis: the [model card](https://huggingface.co/LiquidAI/LFM2.5-350M) gives 188 tok/s on Snapdragon Gen4. A Pi 4 at 5-10x slower ([A]) gives 19-38 tok/s. The old "<300 ms router" target in `CLAUDE.md` is not achievable for a full reply; the `act` field arrives after about 7 generated tokens.

**Arabic quality:** no published WER exists for `tiny` on Arabic that I could find. The closest are fine-tuned `small` at 22-25% WER on Common Voice and 50-74% on dialect sets ([Talafha et al. 2023](https://ar5iv.labs.arxiv.org/html/2306.02902)). Expect `tiny` to be worse. Mitigations: an `initial_prompt` of command words, token-level fuzzy matching, escalation of low-confidence misses to server `small`. Bench B-V3 measures real WER and command accuracy on 200 of the owner's utterances, with gates.

LFM2.5-350M lists Arabic as supported ([V] model card). Token limit tested on real Arabic with the real tokenizer ([V]): worst case 0.78 tokens per character, longest allowed reply 60 characters, so at most 56 tokens with the JSON. `num_predict: 80` holds, and `maxLength: 60` in the schema stops a reply being cut before its closing quote.

### Q3. Does Ollama load the LFM2.5-VL projector?

**Use `llama-server`. Ollama's support is unconfirmed and the evidence conflicts.** Liquid's newer Ollama page shows `ollama run hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF` with no version requirement; a community upload reports projector load errors (`missing tensor`). Liquid's llama.cpp docs state `-hf` fetches the projector and `llama-server` loads both ([V]). The repo already uses `llama-server` for this (`infra/ec2/liquid-vision.service:10`), and `VisionClient` already speaks its API (`vision.py:46`). Nothing in this design depends on Ollama for vision.

### Q4. MQTT over Tailscale against the 1.5 s link timeout and 1.0 s age limit?

**Safe, because the two limits no longer see Tailscale at all.**

- `link_timeout_s` (body `config.py:112`) watches the gateway to body link. Both are on the Pi over loopback.
- `max_cmd_age_s` (body `config.py:113`) used to compare the server's clock with the Pi's. The gateway now stamps every forwarded command with the Pi's clock (fix for D9), so server clock skew cannot reach it.
- Across Tailscale the gateway applies its own rules: 1.5 s source timeout, and a queue-delay check using the minimum one-way delay over 30 s, which needs no synchronised clocks. A Move that sat in a queue over 400 ms is refused; a Stop is never refused.
- Remote Moves are capped at 1.5 s and renewed every 0.5 s, so a dead link can leave at most 1.5 s at 0.06 m/s, or 9 cm, before the Move expires by itself. In practice the 1.5 s source timeout stops it first.

Relay is treated as degraded service, not a safety event. TCP over a DERP relay can stall for seconds; a stall trips the source timeout and the robot stops, which is the correct outcome. Queue delay and `tailscale_path` are shown on the dashboard. [E]: bench B-N1 injects 300 ms, 1 s and 5 s delay with `tc netem`.

### Q5. SLAM stack and recording format?

**Point-LIO, on recorded data, on the server first and AWS on request.** Unitree publishes [`point_lio_unilidar`](https://github.com/unitreerobotics/point_lio_unilidar) with an L2 launch file and config, and names Point-LIO on the [L2 product page](https://www.unitree.com/L2). It uses the L2's built-in IMU and needs per-point time and ring, so the recorder keeps both ([V] SDK header).

Recording format is **SPLR**, a small length-prefixed binary format (`recorder.py`), because the Pi should not carry ROS and a crash must lose at most the last buffer. `infra/slam/rec2bag.py` turns it into a ROS 1 bag with pure Python. Conversion is tested end to end ([V] `VALIDATION.md` §5). Point-LIO itself is unverified: it needs Docker and a real recording. Fallback if it diverges on a hexapod's shaky motion: KISS-ICP, LiDAR-only.

### Q6. What runs where when each part fails alone?

| Failure | Stop and reflexes | Local voice commands | Spoken answers | Remote control | Mapping |
|---|---|---|---|---|---|
| Home server down | Yes | Yes, local STT (slow) | Only short local replies | No; SSH to Pi works | Waits |
| Wi-Fi down | Yes | Yes, local STT (slow) | Only short local replies | No | Recording works |
| Internet down, LAN up | Yes | Yes, fast | Yes, except cloud | Dashboard on tailnet may fail; Telegram no | Server yes, AWS no |
| Gateway dies | Body stops in ≤1.5 s, restart in about 1 s | Back after restart | Back after restart | Back after restart | Unaffected |
| Broker dies | Body stops in ≤1.5 s, restart in about 1 s | Back after reconnect | Back after reconnect | Back after reconnect | Unaffected |
| Voice process dies | Yes | No, until restart in 2 s | No | Yes | Unaffected |
| Ollama dies | Yes | Grammar yes, router no | Filler fails to "ما فهمت" | Yes | Unaffected |
| Brain dies | Yes; a remote Move stops in ≤1.5 s | Yes | No | No; SSH yes | Waits |
| Body dies | Servos are set limp on restart | Commands rejected until restart | Yes | Status only | Unaffected |
| LiDAR dies | Motion refused (`require_lidar`) | Refused with a spoken reason | Yes | Refused | No |

### Q7. Wake word, barge-in, hearing itself, background speech?

- **Background speech cannot move the robot.** Motion needs the wake word near the start of the utterance, which opens a 10 s window (`attention.py`). Stop words bypass this.
- **The wake word is matched in the transcript in the first version**, with no extra model. The cost is that Whisper runs on every speech segment. A dedicated detector (openWakeWord or similar) is a later adapter if bench B-V4 shows the idle CPU load is too high.
- **It cannot stop itself.** `say` text is stripped of stop words before speaking (`clean_say`).
- **It cannot command itself.** Anything overlapping playback, plus 250 ms after, is "deaf": only stop words count.
- **Barge-in, honestly:** while the robot speaks, the pre-stop is off because its own voice would trigger it. To bound that blind window, speech during motion is cut to a 30-character clause, about 1.2 s plus 0.25 s tail ([E]). Echo cancellation (speexdsp) is a later option that needs the speaker and mic on one clock.

## Proposed changes to agreed decisions

**P1. Decision 3: local Whisper `tiny` should be the offline fallback, not the fast path. Configuration only.** Evidence is in Q2. The code keeps the agreed default (`stt.primary: whisper_local`, `escalate: whisper_server`). If bench B-V1 shows local p95 above 2.5 s, as the evidence predicts, change three lines in `voice.yaml`:

```yaml
stt: {primary: whisper_server, fallback: whisper_local, escalate: null}
```

The placement rule still holds: with no network the local path answers, slowly. A 6 s reply to "forward" is working but not good. If the owner wants offline speed too, the candidate is Moonshine Tiny Arabic ([paper](https://arxiv.org/abs/2509.02523)); note its community licence is non-commercial, so it fits a personal robot only. Adding it is one adapter.

**P2. Fact update, not a design change: `moonshotai/kimi-k3.1-pro` has no API yet.** NVIDIA's [model page](https://build.nvidia.com/moonshotai/kimi-k3_1-pro.md), updated 2026-11-04, says "API access for this model is not available yet" and that no API key will authorize it. `moonshotai/kimi-k3` is [listed with text and image input](https://build.nvidia.com/moonshotai/kimi-k3.md). The plan uses `compat:moonshotai/kimi-k3` and treats 3.1 Pro as a one-line config change once its API opens. I could not test either: no accounts.

**No other decision is challenged.** The speech-onset pre-stop adds to Decision 6 and changes nothing in it. On Decision 2, one note: by default peripheral interrupts land on Core 0, so `irqaffinity=1-3` ships with the plan.
