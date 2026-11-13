# Spider robot: roadmap

Each milestone can be tested on its own and leaves the robot working. **A failed gate stops
progress:** no later milestone starts until the gate passes or the plan is changed in writing. Times
are for one developer **[E]**. Step IDs refer to `04_EXECUTION_PLAN.md`, test IDs to
`01_SYSTEM_DESIGN.md` section 9. Nothing from M2 onward has run.

| Milestone | Where | Time **[E]** | Steps |
|---|---|---|---|
| M0 Baseline and CI | Mac | Half a day | S00-S02 |
| M1 Software | Mac | Half a day of execution | S03-S23 |
| M2 Pi bring-up, no motion | Pi, servos unpowered | 2-3 days | P01-P07 |
| M3 First motion on a stand | Pi and robot, owner present | 2 days | P08 |
| M4 Physical E-stop and floor | Robot, owner present | 2-3 days | P09 |
| M5 Voice on the Pi | Pi | 3-4 days | P10 |
| M6 Server, remote, vision, cloud | Server and Pi | 3-4 days | Q01-Q03 |
| M7 Recording, SLAM, AWS | Server, AWS | 3-5 days | Q04 |
| M8 Hardening and cleanup | Ongoing | | Q05 |

Build order: the architecture's order, with hardware gates placed where they catch problems earliest.
RT1 comes before any motion, because if Python cannot hold the loop, everything after it changes. The
physical E-stop comes before floor walking and before voice, so voice testing happens on a robot that
can be stopped by hand.

## M0: Baseline and CI

Commit existing work, install the apply tool, add CI.
**Gate:** S00 ends with a clean tree; S01's hash matches.

## M1: Software

Protocol v3, body safety fixes, gateway arbitration, voice package, brain workers, infrastructure files.

**Gate (S23), all required:** common 25, body 100, gateway 169, voice 120, brain 75 tests pass; `ruff`
clean in all five; `uv lock --check` passes in all five.

## M2: Pi bring-up, no motion

OS, tuning, firewall, broker, certificates, bridge, services. Servo power stays disconnected.

**Gate, all required:**

- HW1: IMU reporting after provisioning; explicit NEGA choice; low and narrow objects recorded in at
  least 8 bearings; mount decided; warm-up time recorded; azimuth histogram logged.
- RT1: R-01 to R-06 on the shipped setting, measured with FIFO and mlock off, then on. **The most
  important gate in the plan.** Records Core 0 load and the camera's interrupt rate.
- NET5: every forbidden publish refused on the real broker; local clients connect with the Pi clock
  at 2000-01-01, and a Stop reaches the body.
- B-F1: `systemd-analyze critical-chain` shows no wait on `network-online.target`; voice-side services
  come up with Wi-Fi off.
- FI1-FI5 with servos unpowered.
- B-F2: 20 hard power cuts, boots every time.

## M3: First motion on a stand (HUMAN)

Robot on a stand, feet in the air, cut-off within reach, owner present. Calibrate. HW2 part one.

Motion goes through `spider-robotctl bench` with `SG_BENCH=1`.

**Gate:** RT2; B1 (logic analyser, no group-move gap over 45 ms); B6 (staged wake, no brown-out); FI1,
FI2 and FI9 with servos powered; no jump on any startup or release.

## M4: Physical E-stop and floor walking (HUMAN)

Fit the switch, relay, fuse, watchdog timer, low-voltage alarm and release button. Move the LiDAR
mount per HW1.

**Gate:** HW2, HW3, HW4, HW5; B-E1 (latch, Wi-Fi off, reboot, release by button only, a short press
does not); RT3, 20 runs. **No untethered walking before this passes.**

## M5: Voice on the Pi

Bench first, integrate after.

**Gate:** V1 and B-V1 set `max_motion_age_s` and decide the `stt.primary` swap; V2 and B-V2 (stop
recall ≥ 95% quiet, ≥ 85% noisy, zero false motion on TV audio); B-V3, B-V4, B-V5; V3; V4; V5 (voice
ready ≤ 90 s with nothing connected); S1 (≥ 98% valid JSON, no truncation); FI6, FI7. If V1 or V2
fails, take the ladder: `base` instead of `tiny`, then a trained keyword spotter. The speech-onset stop
stays off unless false stops are at most 1 per 5 minutes while walking.

## M6: Server, remote control, vision, cloud

Server setup, brain moves from EC2, Tailscale, remote caps, release flow, vision, Kimi via NIM with
`moonshotai/kimi-k3`.

**Gate:** NET1-NET4; B-N1, B-N2; FI8, FI10; V6; B-S1; a remote E-stop release works end to end and is
refused when the challenge is reused; S2 and B-S2, 24 h soak.

## M7: Recording, SLAM, on-demand AWS

**Gate:** the budget alarm is in place first; a recording survives a power cut mid-job; Point-LIO
makes a usable map from a real recording; the worker stops itself with the link home cut.

## M8: Hardening and cleanup

Delete the EC2 and AWS IoT files once M6 has run for two weeks. Optional: keyword spotter if V4 calls
for one, cliff detection with an inverted LiDAR, a server health reporter, a GPU server.

**Gate:** one week of normal use with no unexplained restart.

## What is kept, changed, deleted

**Kept:** the wire protocol's shape; IK and gait; `SafetyGuard` and corridor logic; `MqttLink`; the
planner, graph, tools, policy, memory, skills, Telegram and dashboard; `spider-calibrate`; the PCA9685
driver as an alternative.

**Changed or added:** every file is listed in `02_FILE_MAP.md`. Principal: `protocol.py` (v3),
`robot.py`, `main.py`, `hw/lidar.py`, `hw/servos.py`, `lidar_bridge.cpp`, `gateway.py`, the whole
`voice/` package, `robot_client.py`, `telegram.py`, the units, `setup_pi.sh`, the ACL.

**Deleted, at M8 only:** `infra/ec2/` and the AWS IoT files, as the architecture agreed.

## Top risks, in the order they would be hit

| Risk | Evidence | Mitigation |
|---|---|---|
| IMU disabled from the factory stops all walking | L2 manual and SDK README disagree **[S]** | HW1 provisioning |
| L2 sends no clouds while warming below 30 °C | L2 manual **[S]** | Runbook; HW1 measures it |
| Voice Stop takes seconds | [E] 3.3-8.3 s offline | Expiring Moves; physical E-stop |
| Whisper tiny transcribes Arabic poorly | 63.4% and 90.9% WER **[S]** | Closed vocabulary, fuzzy match, V2 |
| LiDAR blind below the sensor plane, misses narrow obstacles | L2 geometry **[S]** + **[E]** | H-02 mount change; operating rule |
| Core 0 over budget from ZeroMQ wake-ups | Measured path cost scaled **[E]** | `IMU_DECIMATE=10`; `NOBLOCK` drain |
| Inrush browns out the servo rail on stand from limp | Not measured | Staged wake; HW4, B6 |
| `#nP0` may not make the servos limp | Undocumented | HW2; only the power cut is reliable |
| Server memory tight with both models | About 5.7 GB free **[S: brief]** | `MemoryMax`; drop 1.2B first |
| Router slow or truncates on a Pi 4 | No Pi 4 figure | Streaming; S1 |
