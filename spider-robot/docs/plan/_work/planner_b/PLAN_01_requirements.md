# 1. Requirements

Labels as in `PLAN_00_index.md`. "Measured by" names the instrument. Bench IDs are defined in `PLAN_09_testing.md`.

## 1.1 Functional

| ID | Requirement | Owner | Decision |
|---|---|---|---|
| F1 | Walk, turn, stand, sit, relax from short Arabic voice commands | voice, gateway, body | 3 |
| F2 | Stop on a stop word, matched in the transcript with no model | voice | 6 |
| F3 | Stop within about 0.2 s of speech onset while moving, with no model | voice | adds to 6 |
| F4 | Ignore background speech for motion unless addressed by the wake word | voice | Q7 |
| F5 | Never act on its own voice | voice | Q7 |
| F6 | One sender to the body; priority Stop/E-stop from anyone, then voice, remote, planner | gateway | 5 |
| F7 | A Stop stays in force against other equal or lower sources for 2 s, and the displaced owner is told | gateway | 5 |
| F8 | Answer vision and hard questions as speech only | brain workers | 7 |
| F9 | Remote control by Telegram and dashboard, SSH as fallback | brain, infra | 8 |
| F10 | Remote motion has tighter caps than voice, enforced on the Pi | gateway | 8 |
| F11 | Remote E-stop release and wake from limp need a fresh frame and explicit confirmation, enforced on the Pi | gateway | 8 |
| F12 | Safety, motion and simple voice work with no network or cloud | all on Pi | 1 |
| F13 | STT, TTS, LLM, vision are swappable by config | voice, brain | 10 |
| F14 | LiDAR recording and mapping on request; AWS starts only for a requested job and stops itself | body, brain, infra | 9 |
| F15 | Every utterance traceable from speech to motion by correlation ID | all | - |

## 1.2 Non-functional targets

### Control

| ID | Target | Value | Measured by | Status |
|---|---|---|---|---|
| N1 | Tick wake-up lateness, 1 h under full AI load | p99.9 ≤ 10 ms | `RobotState.loop_late_hist` | Unproven; B1 |
| N2 | Worst gap between ticks | ≤ 60 ms | B1 trace log | Unproven; B1 |
| N3 | `loop_overruns` growth | ≤ 1 per 10 min | `RobotState` | Unproven; B1 |
| N4 | Tick execution | p99 ≤ 5 ms | `loop_max_ms` | [E] 1.2-2 ms |
| N5 | SSC-32U group move spacing while walking | 40 ± 3 ms, no gap over 45 ms | Logic analyser on one channel | Fixed in simulation [V]; B1 on hardware |
| N6 | Obstacle reflex: cloud to stop command | ≤ 150 ms | B5 with a board placed in the path | [E] |
| N7 | Fall to servos limp | ≤ 200 ms past 55° | B5 on a stand, tilted by hand | [E] |

### Stop

| ID | Target | Value | Measured by | Status |
|---|---|---|---|---|
| N8 | Speech onset to Stop sent | p95 ≤ 200 ms | Trace stage, plus audio click and logic analyser in B-V5 | [E] 100-140 ms |
| N9 | Stop sent to body handling it | p95 ≤ 20 ms | Gateway and body logs by `cid` | [E] |
| N10 | Stop handled to zero commanded velocity | ≤ 0.35 s at voice speed; ≤ 0.5 s at top speed | Computed: v/accel [V]; `RobotState.vx` | 0.32 s at 0.08 m/s; 0.48 s at 0.12 m/s |
| N11 | Stop word in transcript to Stop sent | ≤ 5 ms | Trace | [E] |
| N12 | Stop word end of speech to Stop sent, online | p95 ≤ 2.5 s | Trace | [E] 1.3-2.4 s |
| N13 | Stop word end of speech to Stop sent, offline | p95 ≤ 8.5 s | Trace | [E] 3.3-8.3 s. **Too slow to rely on: F3 is what protects people offline** |
| N14 | Telegram Stop to robot | p95 ≤ 3 s | Manual B-N2 | [E] |

### Voice, end of speech to first effect

| ID | Stage | Target p95 | Status |
|---|---|---|---|
| N15 | VAD close | 300 ms configured | [V] `hang_ms` |
| N16 | STT on server (`small`, int8) | ≤ 2.0 s | [E] 0.8-2.0 s; B-V2. If exceeded, use `base` |
| N17 | STT local (`tiny`, int8) | none achievable below 3 s | [E] 3-8 s; B-V1 |
| N18 | Grammar match | ≤ 5 ms | [E] |
| N19 | Router first `act` | ≤ 1.2 s | [E] 0.6-1.2 s; B-V2 |
| N20 | Router full reply | ≤ 2.5 s | [E] 1-2.5 s; B-V2 |
| N21 | First audio, canned phrase | ≤ 100 ms | [E]; B-V2 |
| N22 | First audio, Piper | ≤ 1.0 s | [E] 0.3-1.0 s; B-V2 |
| N23 | Vision answer on the server | ≤ 30 s | [E] 5-20 s; B-S1. Timeout is set from the measured p95 |

### Availability per failure mode

Function table in `PLAN_00_index.md` Q6. Numeric targets:

| ID | Target | Value | Measured by |
|---|---|---|---|
| N24 | Automatic recovery after a process crash | ≤ 5 s for gateway, broker, voice; ≤ 15 s for body | FI tests |
| N25 | Pi services up after boot with no network | All local services, ≤ 90 s | B-F1 with Wi-Fi off |
| N26 | Robot stops after owner source loss | ≤ 1.75 s (1.5 s timeout plus one 4 Hz tick) | FI-3 |
| N27 | Robot stops after gateway or broker loss | ≤ 1.5 s plus one tick | FI-4, FI-5 |
| N28 | 24 h soak | 0 process restarts, 0 unexplained stops, memory growth ≤ 1 MB/h per service | B-S2 |

### Resources

| ID | Target | Value | Measured by |
|---|---|---|---|
| N29 | Core 0 average load | ≤ 60% | `pidstat -u -p`, B1 |
| N30 | Pi total RSS, all services loaded | ≤ 2.2 GB | B-S2 |
| N31 | Pi CPU temperature, 30 min full voice load with cooling | ≤ 75 °C, no throttle bits | `spider-health`, B3 |
| N32 | Server memory used by this project | ≤ 5.0 GB with all models loaded | `systemctl status`, B-S1 |
| N33 | Pi flash writes in normal operation | ≤ 50 MB/day | `iostat`, B-S2 |

### Security and operations

| ID | Target | Value | Measured by |
|---|---|---|---|
| N34 | Open ports reachable from LAN on the Pi | SSH only (plus 8883 on tailscale0) | `nmap` from another host |
| N35 | Update of a running robot | Refused unless sitting or relaxed; rollback ≤ 60 s | Deploy test |
| N36 | AWS worker running with no job | ≤ 15 min idle; hard limit 4 h | Timer test on the instance |

## 1.3 What cannot be met on this hardware

| Wanted | Reality | Best achievable |
|---|---|---|
| Router under 300 ms (`CLAUDE.md`) | Unattainable for a full reply [E] | `act` read from the stream at about 0.6-1.2 s; grammar hits skip the LLM |
| Sub-second local STT | 3-8 s [E] | Server STT when reachable, about 1-2 s; pre-stop on speech onset |
| Stop by word in under 1 s offline | STT time dominates [E] | Pre-stop at 0.13 s after onset |
| Barge-in while speaking | Own voice masks the speaker without echo cancellation | Blind window bounded to about 1.45 s while moving |
| Software-only E-stop that removes energy | Software cannot cut servo power | Hardware cut of VS1 and VS2, `PLAN_06_safety.md` |
