# Planner A: spider robot engineering plan

Author role: principal robotics and real-time systems engineer. Priorities, in order: physical
safety, determinism, failure containment. Written 2026-11-09/10 against branch
`robot/spider-robot/part2-brain` including its uncommitted work.

File references without a package prefix are given as `package/path:line` and refer to the code as
it stood at baseline, before `code.patch`.

## How to read the evidence

Every number and claim carries one of these labels.

| Label | Meaning |
|---|---|
| **[V]** | Verified here: code read at the cited line, or a test or script actually run (`VALIDATION.md`) |
| **[S]** | From a published source, named with its date in `PLAN_11_cost.md` or inline |
| **[E]** | Estimated. Always states its basis and the bench test that replaces it |
| **[A]** | Assumed. Nothing in hand supports it yet |

Nothing here has run on the real Pi, a real broker, the real server, or real servos.

## Parts

| File | Required item |
|---|---|
| `PLAN_01_requirements.md` | 1. Requirements and numeric targets |
| `PLAN_02_architecture.md` | 2. Context and container diagrams, responsibilities, data flows |
| `PLAN_03_contracts.md` | 3. Topics, messages, interfaces, compatibility |
| `PLAN_04_budgets.md` | 4. CPU, RAM, bandwidth, latency budgets |
| `PLAN_05_failure_analysis.md` | 5. FMEA and single-failure table |
| `PLAN_06_safety.md` | 6. Hazards, states, what the E-stop cuts |
| `PLAN_07_security.md` | 7. STRIDE |
| `PLAN_08_observability.md` | 8. Logs, metrics, traces, health, alerts |
| `PLAN_09_testing.md` | 9. Test levels and the bench test catalogue |
| `PLAN_10_delivery.md` | 10. CI, installs, units, secrets, updates, runbooks |
| `PLAN_11_cost.md` | 11. Monthly cost with sources |
| `PLAN_12_adrs.md` | 12. ADRs, and "Proposed changes to agreed decisions" |
| `PLAN_13_roadmap.md` | 13. Milestones, gates, kept / changed / deleted |
| `PLAN_14_open_questions.md` | The seven open questions, settled |
| `FILE_MAP.md` | Every file, with package, node and milestone |
| `code.patch` | Complete code, applies with `git apply` from the repo root |
| `VALIDATION.md` | Commands run and their real output |

## The design in one page

The robot is a statically stable hexapod. With a tripod gait, three feet are always on the ground
(`body/src/spider_body/gait.py:22`), and nothing closes a fast balance loop. That one fact shapes the
real-time design: **a late tick costs nothing, a long stall costs a pause, and the dangerous failures
are the ones where the software believes something false about the world.** The review therefore
looked hardest for false beliefs, and found several (below).

- **Core 0:** `lidar_bridge` and `spider-body`, the latter as a single `SCHED_FIFO` thread with locked
  memory. Python is good enough for this loop, on conditions that a one-hour bench gate proves.
- **Cores 1-3:** broker, gateway, voice, Ollama, camera, recorder.
- **Gateway:** the only sender to the body. It re-stamps every command with its own clock, judges
  lateness without trusting the sender's clock, applies per-source caps, and enforces the remote
  E-stop release rule on the Pi.
- **Voice:** stop words first, on the transcript, with no wake word and no model. Then wake word, then
  a deterministic grammar, then the LLM with a lexical cross-check. Vision and cloud answers can only
  be spoken.
- **Motion is bounded at the source.** Every Move expires by itself: at most 2.0 s for voice and 1.0 s
  for remote. This bound, not a stop command, is the primary protection when something fails.
- **Hardware E-stop:** a physical switch cutting servo power, required before the robot walks
  untethered. The software E-stop freezes the pose and does not remove torque.

## What cannot meet its target on this hardware

| Item | Target people expect | Best achievable here | Alternative |
|---|---|---|---|
| Voice Stop | under 1 s | about 1.4-2.9 s from end of speech to the start of braking **[E]** | Moves expire on their own within 2 s; hardware E-stop; speech-onset stop after bench test V4; a trained keyword spotter (M8) |
| Router latency | under 300 ms | first token likely 0.3-1 s **[E]**; the whole reply takes longer | Grammar path answers common commands in under 1 ms **[V, on the Mac]** |
| Arabic transcription | good dictation | Whisper tiny 63.4% WER on Arabic FLEURS **[S]** | Closed-vocabulary commands, fuzzy match, escalation to Whisper small on the server |

## Defects found in the existing code

The first nine were reproduced by running the unmodified baseline: `VALIDATION.md` section 3 has the
script's output. All are fixed in `code.patch`, each with a regression test, unless marked.

| # | Defect | Where | Consequence | Reproduced |
|---|---|---|---|---|
| D1 | A sector not swept by the current LiDAR cloud is reported as free (8 m). One cloud covers about 166° of azimuth | `body/src/spider_body/hw/lidar.py:75-79,130`, `body/lidar_bridge/lidar_bridge.cpp:71` | Over half the obstacle map is false at any instant; the planner and turn reflex read it | **Yes**: sector 0 went 1.0 → 8.0 |
| D2 | Body-pose ramp keeps running under an E-stop | `body/src/spider_body/robot.py:304-308,327` | Servos moved **34.3°** after E-stop in the reproduction | **Yes** |
| D3 | Height ramp keeps running under an E-stop, so feet jump on release | `robot.py:306`, `gait.py:108-111,155` | **32.8°** servo jump within 60 ms of release | **Yes** |
| D4 | SIGTERM under a latched E-stop clears the latch and sits the robot down | `body/src/spider_body/main.py:132-136` | Motion during an E-stop on any `systemctl restart` | **Yes** |
| D5 | E-stop latch does not survive a process restart | `robot.py:81`; `body/systemd/spider-body.service:19` (`Restart=always`) | A crash silently un-latches the E-stop | **Yes** |
| D6 | Any parsed command refreshes the link watchdog before the version check | `robot.py:110-117` | A wrong-version sender keeps the link "alive" | **Yes** |
| D7 | Gateway has no per-source caps | `gateway/src/spider_gateway/gateway.py:113-116` | Remote can command the protocol maximum, against agreed decision 8 | **Yes** |
| D8 | A heartbeat delayed in a TCP backlog marks its source alive | `gateway.py:89` | A stalled remote link looks healthy | **Yes** |
| D9 | Remote E-stop release has no frame or confirmation check | `gateway.py:104-106`, `brain/src/spider_brain/telegram.py:202-204`, `brain/src/spider_brain/supervision/server.py:93-94` | Against agreed decision 8 | **Yes** |
| D10 | After a crash the SSC-32U keeps its last pulses but the new process assumes relaxed | `body/src/spider_body/main.py:160-162`, `robot.py:80,200-204` | Next `stand` commands a full-speed jump from an unknown pose | By reading |
| D11 | Camera capture and JPEG encoding run inside the control process, and OpenCV loads at import | `robot.py:149,227`, `hw/camera.py:17` | Against agreed decision 3; CPU and RAM on Core 0 | Test proves the fix |
| D12 | `body/lidar_bridge` publishes every IMU sample (500 Hz **[S]**) into the control loop's event loop, sharing a 2-message receive queue with clouds | `lidar_bridge.cpp:105-114`, `hw/lidar.py:152,157` | Avoidable wake-ups on Core 0; clouds can be dropped | By reading |
| D13 | IMU low-pass was never tuned for the real sample rate, and raw samples can alias foot impacts | `hw/lidar.py:141` | Tilt estimate is noisier than intended | By reading |
| D14 | Bridge polls at up to 5 kHz | `lidar_bridge.cpp:116` | Needless wake-ups on Core 0 | By reading |
| D15 | Timing metrics cannot show jitter: overruns count only missed deadlines, `loop_max_ms` only tick duration | `main.py:81,87-91` | Open question 1 could not be answered from telemetry | By reading |
| D16 | Stop-distance check assumes 0.1 s of detection delay; the L2 can take about 0.26 s | `config.py:168-169` | Unsafe configurations would pass validation | Test proves the fix |
| D17 | Gateway's cross-source fence and body's age check rely on sender wall clocks | `gateway.py:110,137`, `robot.py:123-125` | Remote control needs NTP to be working; clock skew blocks or misorders commands | By reading |
| D18 | Stop does not end a height or pose change in progress | `robot.py:145-147` | "Stop" during stand-up keeps moving | Test proves the fix |
| D19 | `lidar_bridge` never sets the work mode. Unitree's manual says the IMU is **disabled** at the factory, its SDK README says enabled | `lidar_bridge.cpp:70-77`; manual and README **[S]** | If the manual is right, the robot refuses to walk (`robot.py:277-280`) with no obvious reason | Bench HW1 decides |
| D20 | The planner and the owner share one gateway source | `brain/src/spider_brain/service.py:82` | Agreed priority of remote over planner cannot work | Test proves the fix |

### Open physical finding: the LiDAR cannot see low obstacles if mounted upright

**[S]+[E]** The L2 field of view is a hemisphere, 90° vertical, or 96° with the extra 6° below the
horizon in NEGA mode (L2 manual). Upright, at `mount_height_m: 0.15`
(`body/config/robot.example.yaml:30`), the lowest visible height at horizontal distance *r* is
`0.15 - 0.105 r`. At the stop boundary (about 0.40 m from the centre) that is **about 11 cm**. Anything
lower is invisible there: shoes, cables, a pet lying down, and any stair edge. The reflex
`z_min_m: 0.04` suggests the design assumed otherwise. Software cannot fix this. Bench HW1 confirms
the geometry, and H-02 in `PLAN_06_safety.md` gives the mounting options. This is the largest open
physical risk in the plan.

## Top decisions

1. Keep Python for the 50 Hz loop, conditional on gate RT1, with a defined ladder if it fails (ADR-01).
2. Fence all of user space off Core 0 with a systemd default, steer IRQs away, and use `SCHED_FIFO`
   plus `mlockall` on one thread only. No `isolcpus`, no PREEMPT_RT at first (ADR-02).
3. Bound motion at the source with short self-expiring Moves (ADR-03).
4. The gateway judges lateness with a minimum-delay filter per source, and re-stamps commands, so
   nothing depends on NTP (ADR-04).
5. The E-stop latch is persistent, and a process that starts latched sends nothing to the servos
   (ADR-05).
6. A physical power cut is required before untethered walking (ADR-06).
7. Grammar before LLM, and the LLM may only choose a motion the owner's words name (ADR-07).
8. `llama-server` for vision, because Ollama's projector loading could not be confirmed (ADR-09).

## What I could not do

- **Ollama and real LFM2.5 output.** I tried to download the Ollama binary into my scratch area to
  test projector loading and Arabic JSON output. The permission system denied it and I did not look
  for a way round it. Those two remain **unverified**; bench V2 and S1 replace them. The Arabic token
  budget *is* measured, with the real LFM2.5-350M tokenizer file.
- **A real Mosquitto broker.** Not installed here, so MQTT, TLS and ACL behaviour are unverified until
  gate M1.
- **The `lidar_bridge` change** was syntax-checked against stubs I wrote from the published SDK
  headers, not compiled against the SDK. CI builds it against the real SDK.
