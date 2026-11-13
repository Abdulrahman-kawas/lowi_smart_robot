# 13. Roadmap

Each milestone is independently testable and leaves the robot working. Order follows the agreed build order, with a safety milestone before any motion. Gates are defined in `PLAN_09_testing.md` §9.4. Times are rough estimates for one developer working evenings [A].

## What is kept, changed, deleted

| Area | Disposition |
|---|---|
| Body: IK, gait, safety guard, kinematics, calibration | **Kept** unchanged |
| Body: main loop, robot state machine, servo rate gate, LiDAR feed, camera | **Changed** (D2-D5, D7) |
| Gateway: arbitration idea and interface | **Kept**; internals rewritten |
| Gateway: `_stop_ts` timestamp comparison | **Deleted** in the rewrite, replaced by hold-off and restamping |
| Brain: planner, graph, policy, memory, skills, WhatsApp, voice notes | **Kept** unchanged |
| Brain: robot client, Telegram, dashboard, service, vision | **Changed** |
| Three gateway tests | **Changed**: future-clock, release, and the simulated-body test (see `VALIDATION.md` §3) |
| `infra/local` | **Changed** |
| `infra/ec2`, `infra/aws` IoT parts | **Kept until M7**, then deleted |
| Voice | **New** package |

## M0 Baseline and physical prerequisites (2-3 evenings)

Apply the patch, tests green on Mac and Pi.

**HUMAN STEPs:** install the hardware E-stop, fuses, separate Pi and VL regulator (`PLAN_06_safety.md` §6.4). Active cooling. Choose mic and speaker.

Gate: §9.4 M0.

## M1 Gateway, body hardening, Pi broker (1-2 weeks)

1. `setup_pi.sh`, passwords, broker, firewall.
2. `spider-lidar`, `spider-gateway`, health. Simulator against real Mosquitto: first time on a real broker.
3. **B1 at L0.** Most important measurement in the plan; do it before voice exists to confuse it. Start with a synthetic load on cores 1-3.
4. B5, B6, on a stand.
5. First powered motion: HUMAN STEP.

Robot state after: walks by `spider-brain teleop` through the gateway, with reflexes.

## M2 Voice on the Pi (1-2 weeks)

1. Install Ollama, Piper, Whisper. `spider-voice` with the agreed local config.
2. Record the 200-utterance corpus. **B-V1, B-V2 (local), B-V3.**
3. Extend the grammar from what B-V3 misses.
4. B-V4 and B-V5: false triggers; real Stop timing.

Robot state after: obeys voice with no network, slowly.

## M3 Brain on the home server (1 week)

1. `setup_server.sh`, certificates, `SB_ROBOT_SOURCE=planner`, `SB_HUMAN_SOURCE=remote`.
2. B-S1: set timeouts from measured values.
3. Turn on ask and STT workers. Apply P1 if B-V1 says so.
4. B-V2 and B-V3 on server STT.

Robot state after: fast commands at home, and spoken vision answers.

## M4 Remote control (1 week)

1. Tailscale, tailnet policy, `tailscale serve` for the dashboard.
2. Telegram two-step verification (owner).
3. `nmap`, B-N1, B-N2, FI-8, FI-14, FI-15.
4. Guarded remote session, room cleared.

Robot state after: remote control within caps; confirmed release.

## M5 Cloud escalation (2-3 evenings)

`SB_ASK_FALLBACK=compat:moonshotai/kimi-k3`. Check whether the 3.1 Pro API has opened. Accept the privacy note. Confirm failure is spoken.

## M6 Recording and mapping (1-2 weeks)

1. `spider-record`, one recording, walking. Confirm no effect on `loop_late_hist`.
2. Server: convert and run Point-LIO. **This is the first real test of that stack.** Fallback to KISS-ICP if it diverges.
3. AWS: instance, IAM, budget alarm first (HUMAN STEP), self-stop tested idle and at the limit. Only then enable.

## M7 Soak and cleanup (1 week, mostly waiting)

B-S2, B-F1, B-F2. Delete the AWS IoT and EC2 parts per `FILE_MAP.md`. Update `ARCHITECTURE.md` with measured numbers.

## Order of risk

What I expect to break first on real hardware, so it is tested earliest:

| # | Risk | Where it shows up | Tested at |
|---|---|---|---|
| 1 | Servo noise makes VAD fire constantly while walking, so pre-stop halts every walk | Mic mounted near servos | M2, B-V4 |
| 2 | Servo current sags the rail and resets the Pi | First stand | M1, B4 |
| 3 | Core 0 cannot keep up with L2 traffic even after decimation | Loop lateness | M1, B1 |
| 4 | Arabic STT accuracy is too low for command use, even on `small` | Every voice command | M2, B-V3 |
| 5 | Heat in an enclosure | After 10 minutes of talking | M2, B3 |
| 6 | `#nP0` does not stop pulses on the SSC-32U | Relax and limp behaviour | M1, B6 |
| 7 | Ollama cannot run this LFM2.5 build or honour `maxLength` | First router call | M2, B-V2 |
| 8 | Point-LIO diverges on walking motion | First map | M6 |
