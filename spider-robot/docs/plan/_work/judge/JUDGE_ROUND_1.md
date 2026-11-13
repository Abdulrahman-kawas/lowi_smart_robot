# Judge round 1

Judge run on 2026-11-10 on a Mac (Apple Silicon, macOS, uv 0.12.17). Nothing touched a Pi, a server,
the robot, a broker of the owner's or a cloud account. Labels used throughout: **[V]** verified by me
(code read at the cited line, or run by me); **[S]** from a named published source; **[E]** estimated;
**[A]** assumed. `file:line` refers to the baseline tree unless prefixed `A:` or `B:` (the patched copy).

## 1. Real test results

Three fresh copies made with the brief's rsync command, one baseline commit each. `git apply --check`
then `git apply` succeeded for both patches. SHA-256 of B's patch matches its VALIDATION
(`c50e4895...`); A's patch is `64d5cc29...`.

| Package | Baseline | Plan A | Plan B | Ruff (all three) |
|---|---|---|---|---|
| common | 9 passed | 15 passed | 24 passed | All checks passed |
| body | 47 passed | 88 passed | 60 passed | All checks passed |
| gateway | 16 passed | 37 passed | 101 passed | All checks passed |
| voice | absent | 87 passed | 81 passed | All checks passed |
| brain | 33 passed, 2 warnings | 58 passed, 2 warnings | 70 passed, 2 warnings | All checks passed |
| **Total** | **105** | **285** | **336** | |

Both `VALIDATION.md` test tables are accurate [V]. The two brain warnings are a third-party
`SyntaxWarning` in `google/genai/types.py` and are present at baseline.

Raw output: `<judge scratch>/results_{baseline,a,b}.txt`.

### 1.1 Priority defects reproduced on unmodified baseline

Independent script (mine, not the planners'), run against the baseline packages:

```
A-D1 sector[0] 1.0 -> 8.0 (8.0 = 'free')
A-D2 pitch after estop 0.052 -> 0.262 rad; max servo change 34.3 deg; mode=estop
A-D3 height 0.055 -> 0.090; servo change during estop 0.0 deg; jump within 60 ms of release 32.8 deg
A-D4 after sit_and_relax under estop (estop, mode, target_height): (False, 'sitting', 0.035)
A-D5 first process estop: True  new process estop: False relaxed
A-D6 last_link refreshed by v=1 heartbeat: True 100.0
A-D7 forwarded remote move: 0.5 2.0 10.0
A-D8 stale heartbeat, commands sent: ['move', 'heartbeat'] (no 'stop' = stalled source kept alive)
A-D9 remote release with no frame or confirmation: ['estop_release']
B-D1 body sees: ['move', 'stop', 'move']  planner events: []
B-D2 sigma=0.0ms sends=2500 mean=40.0ms pct_gt45ms=0.0% max=40.0
B-D2 sigma=0.2ms sends=1964 mean=50.9ms pct_gt45ms=54.6% max=60.6
B-D2 sigma=0.5ms sends=1939 mean=51.6ms pct_gt45ms=57.8% max=61.6
B-D2 sigma=1.0ms sends=1934 mean=51.7ms pct_gt45ms=58.5% max=63.2
B-D2 sigma=2.0ms sends=1930 mean=51.8ms pct_gt45ms=62.1% max=66.4
```

Every priority claim is real on baseline code [V]. B's servo-slip numbers differ from its own by a
few percent because the jitter seed differs; the conclusion stands.

### 1.2 Do the tests prove anything? Mutation check [V]

For each critical fix I broke that one fix in the patched code, ran the package's tests, and restored
it. Script: `<judge scratch>/scripts/mutate.py`.

| Plan A mutation | Result | Plan B mutation | Result |
|---|---|---|---|
| D8 stale heartbeat counts as alive | caught | Stop hold-off removed | caught |
| D7 no per-source cap | caught | No per-source cap | caught |
| D9 release refusal removed | caught | Challenge expiry and hash unchecked | caught |
| Stop fence removed | caught | Challenge reusable | caught |
| No re-stamp (D17) | caught | No re-stamp | caught |
| D2/D3 ramps run during E-stop | caught | Queue-delay check removed | caught |
| D4 shutdown clears latch | caught | Wake rule removed | caught |
| D5 latch ignored at start | caught | Servo slip fix reverted | caught |
| D6 version check after watchdog | caught | Sector merge removed | caught |
| D1 sector merge removed | caught | Version check after watchdog | caught |
| D18 Stop does not end ramps | caught | Staged wake removed | caught |
| LLM cross-check removed | caught | Pre-stop removed | caught |
| Stop word ignored | caught | Stop word ignored | caught |
| Long-utterance busy gate removed | caught | Own speech not stripped | caught |
| **Startup relax removed (D10)** | **NOT caught (88 passed)** | **Limp at startup removed** | **NOT caught (60 passed)** |

Result: 14 of 15 caught in each. The one fix neither plan tests is the same fix. New tests in both
plans exercise real behaviour: the gateway tests drive the real `Gateway`, the body tests drive the
real `Robot` with a fake servo bank, and both plans have end-to-end tests through gateway and simulated
body. Fakes stop at the engine boundary (Whisper, Piper, Ollama), which is honest but means the real
adapters have never run.

Test counts need one caution: B's "101 gateway tests" are 53 test functions expanded by
`parametrize` (mostly ACL client x topic combinations). A has 37 functions and 37 tests there. Counts
are not comparable; the mutation result is the better measure.

### 1.3 Existing tests the planners changed

| Plan | Test | Change | Verdict |
|---|---|---|---|
| A | `gateway/tests/test_gateway.py` helper `beat()` and timestamp arguments | Timestamps now move with the clock | Legitimate: the lateness filter needs real timing |
| A | `test_stop_with_future_clock_does_not_block_other_sources` | Waits out the 0.75 s fence | Legitimate |
| A | `test_lost_owner_stops_robot_and_voice_keeps_the_link` | Move duration 9.0 changed to 0.9 | Not weakened in its assertions, but it no longer shows a halt during a Move: with a 1.0 s cap and a 1.5 s source timeout a remote Move always expires first, so the test now passes on owner loss alone. Accepted, noted |
| A | `test_only_owner_side_sources_can_release_estop` | Replaced by two tests | Legitimate: the old test asserted the defect |
| A | `brain/tests/test_robot_source.py:24` | `==` changed to `<=` | **Weakened.** A subset assertion passes when nothing is published at all. Required change R-22 |
| B | `test_stop_with_future_clock_does_not_block_other_sources` | Waits out the 2 s hold-off | Legitimate |
| B | `test_only_owner_side_sources_can_release_estop` renamed | Every source refused without a confirmed frame | Legitimate: the positive path is covered by new challenge tests |
| B | `test_simulated_body_stops_when_remote_source_disappears` | Voice stands the robot, because remote may not wake it | Legitimate; the property under test is unchanged |

A's other changed test file (`common/tests/test_protocol.py`) only adds tests; the single removed line
is an import that was widened.

## 2. Claim verification

"Confirmed" means I read the cited line or ran it. Each row names the evidence.

### 2.1 Plan A

| Claim | Verdict | Evidence |
|---|---|---|
| D1 unswept sector reads free | **Confirmed, but the size is overstated** | Reproduced (section 1.1). `lidar.py:75-79,130`. A says one cloud covers "about 166 deg" and "over half the obstacle map is false at any instant". The L2 manual (PDF p.8) says the mirror covers "180° in the vertical direction", i.e. horizon to horizon through the top, so each scan samples both sides of the rotation axis. A cloud of 18 scans at 9.25 deg per scan covers about 333 deg of azimuth, leaving about 27 deg unswept. [S]+[E]; HW1 settles it with an azimuth histogram. The fix is still needed |
| D2, D3 ramps run under E-stop | Confirmed | 34.3 deg and 32.8 deg reproduced exactly. `robot.py:304-308,327` |
| D4 SIGTERM clears latch | Confirmed | `main.py:132-136`, reproduced |
| D5 latch lost on restart | Confirmed | `robot.py:81`, reproduced |
| D6 wrong-version heartbeat feeds watchdog | Confirmed | `robot.py:110-117`, reproduced |
| D7 no caps, D8 stale heartbeat, D9 release with no proof | Confirmed | Reproduced. `gateway.py:113-116`, `:89`, `:104-106` |
| D10 restart assumes relaxed | Confirmed by reading | `main.py:160-162`, `robot.py:80,200-204`. Fix present, untested (section 1.2) |
| D11 camera and OpenCV in control process | Confirmed | `robot.py:149,227`; `hw/camera.py:17` |
| D12 every IMU sample wakes the loop | Confirmed | `lidar_bridge.cpp:105-114`; manual: 500 Hz report |
| D13, D14, D15, D16, D17, D18, D20 | Confirmed by reading | `lidar.py:141`; `lidar_bridge.cpp:116`; `main.py:81,87-91`; `config.py:168-169`; `gateway.py:110,137`; `robot.py:145-147`; `service.py:82` |
| D19 IMU may be off from the factory | **Confirmed, and it matters** | Manual PDF p.4: "factory default parameters are: 3D Mode, NEGA Mode, IMU Disable". SDK README: "default factory lidar work mode is 0", where bit 2 = 0 enables the IMU. The manual also contradicts itself on NEGA (PDF p.13: "defaults not to open the negative angle mode") |
| Low obstacles invisible when upright | **Confirmed, and worse than stated** | Manual: 360x90, or 360x96 in NEGA. A's arithmetic (0.15 - 0.105 r = 10.8 cm at 0.40 m) is right for NEGA. In normal mode nothing is seen below the sensor plane at all, so the limit is 15 cm at every range |
| Self-heating below 30 C, no clouds until warm | Confirmed | Manual, PDF p.18 notes |
| Whisper tiny 1.0-2.5 s on a Pi 4 | **Rejected** | Unsupported by any source, and A states "No published Pi 4 figure" when figures exist: 35 s for 100 s of audio with tiny on a Pi 4 (MaibornWolff, implementation unnamed); tiny encode 13.8 s, 4 threads (whisper.cpp #89, old build). Neither is int8 Arabic, so no figure is exact, but all point above A's range |
| Whisper tiny 63.4% WER | Accurate, **selective** | arXiv 2510.23319 Table 7. The same table gives 90.9% on Common Voice 9 Arabic, omitted by A and closer to dialect speech |
| Core 0 budget 15-25% | **Understated** | A assumes 0.15 ms per asyncio wake-up on the Pi. I measured 212-296 us per message on Apple Silicon, so about 1.3-3 ms on a Pi at the 6-10x factor both planners assume [E]. See section 3, item 13 |
| Boot CPU cannot be `nohz_full` | Partly stale | Allowed since commit 08ae95f4fd3b (2019). Weisbecker, April 2024: "possible", "only half-working". Moot on this hardware: `bcm2711_defconfig` (rpi-6.12.y) sets `CONFIG_NO_HZ=y` with no `NO_HZ_FULL` |
| Ollama v0.40.15, llama.cpp v0.9.0 | Confirmed | GitHub API: both latest, 2026-11-03 and 2026-11-04 |
| `kimi-k3.1-pro` has no API; `kimi-k3` hosted | Confirmed | NVIDIA pages, updated 2026-11-04; kimi-k3 lists text and image input, trial terms |
| Point-LIO supports the L2 | Confirmed | `mapping_unilidar_l2.launch`, Ubuntu 20.04, Noetic |
| Prices | Confirmed where checked | c7i.4xlarge Tokyo $0.8988/h (aggregators); Opus 5.5 $4/$20 and Haiku 5.5 $0.10/$0.50 at claude.com/pricing |

### 2.2 Plan B

| Claim | Verdict | Evidence |
|---|---|---|
| D1 voice Stop does not end a walk | Confirmed | Reproduced: `['move','stop','move']`, no event to planner. `gateway.py:97-103,107-116` |
| D2 servo group moves slip | Confirmed | Reproduced: mean 50.9-51.8 ms against 40, with 55-62% of gaps over 45 ms. `servos.py:194` |
| D3 IMU wake-ups are the real cost | Confirmed | My measurement: 212 us/msg at 500 Hz, 11.2% of an Apple Silicon core. Agrees with B's 256 us |
| D4 camera on Core 0; D5 lateness invisible | Confirmed | `robot.py:225-231`; `main.py:67,81` |
| D6 release has no frame or confirmation | Confirmed | Reproduced (same as A-D9) |
| D7 restart assumes relaxed | Confirmed by reading | Fix present, untested (section 1.2) |
| D8 one brain source | Confirmed | `config.py:28`, `service.py:82` |
| D9 clock skew reaches the body | Confirmed by reading | `gateway.py:110,128,137` |
| D10 E-stop cuts nothing electrical | Confirmed | `robot.py:132-138` |
| Local Whisper tiny 3-8 s | Supported as an estimate | Sources above. The 5-6 s Home Assistant report was not checked by me |
| No published WER for tiny on Arabic | **Wrong** | arXiv 2510.23319 Table 7 |
| Core 0 can be `nohz_full` on current kernels [V] | **Overclaimed** | The commit exists; the same LKML thread calls it "half-working", and the stock Pi kernel does not enable it |
| Ollama 0.32.6 is the newest found | **Wrong** | v0.40.15 was published 2026-11-03 |
| `use_identity_as_username` with a global password file [unverified] | Now resolved | mosquitto.conf(5): "the password_file option will not be used for this listener" |
| Protocol stays v2 because changes are additive | **Loose** | B's own R2 says an old Pi rejects the new `cid` field because commands forbid extras. That is an incompatible change without a bump |

## 3. Hardware attack: what breaks first

Ordered by how soon the owner would hit it. Outputs are from `<judge scratch>/attack_a.out`,
`attack_b.out` and `zmq_cost.out`. "Both" means it survives in the patched code of both plans.

| # | Where | What breaks | Evidence | Status |
|---|---|---|---|---|
| 1 | Both | **Boot with no network.** Every safety-relevant unit has `After=network-online.target` and `Wants=` it. Debian's own `mosquitto.service` does too. With Wi-Fi down, body, gateway, LiDAR and broker wait for `network-online.target` to time out [E: tens of seconds], against agreed decision 1 and the plans' own ≤ 90 s boot targets | `spider-body.service:3-4`, `spider-gateway.service:3-4`, `spider-lidar.service:3-4` in both patches | R-12 |
| 2 | B | **Walking is refused for no visible reason.** If the manual's "IMU Disable" factory default is true, tilt stays `None` and `robot.py:277-280` blocks all motion. B has no provisioning step | Section 2.1 D19. A has `LIDAR_SET_WORK_MODE` and `test_stand_is_refused_*` | R-07 |
| 3 | Both | **L2 self-heats below 30 C and sends no clouds.** A normal room start means `lidar_stale` for an unmeasured warm-up period. A has it in the runbook; B does not mention it | Manual, PDF p.18 notes | R-07 |
| 4 | B default | **Gait noise stops every walk.** `pre_stop.enabled: true` (B `config.py:92`). The microphone is on a robot with 18 servos. B itself ranks this as risk 1 and still ships it on | B `PLAN_13` risk table | R-14 |
| 5 | Both | **Voice Stop is slow.** Local tiny is [E] 3-8 s from the published sources, not 1-2.5 s. Offline voice Stop to braking is therefore [E] 3.3-8.3 s. Self-expiring Moves and the hardware E-stop are the real protection, as A's ADR-03 says, but A's numbers understate why | Section 2.1 | R-11 |
| 6 | B | **A Stop can be lost.** Utterances go through one worker and `deque(maxlen=2)`. A Stop arriving during STT waits behind it, and two later segments evict it: `Stop then two later segments while busy; stop commands sent: 0 dropped counter: 1`. `Stop published 1.01 s after it was said behind one 0.5 s STT job` | B `pipeline.py:103,177-181,420-429`, `stt_whisper.py:28`; B5, B6 | R-03 |
| 7 | A | **Stale motion from a backlog.** Short utterances are spawned without limit (A `pipeline.py:120-128`) and nothing checks an utterance's age. In a noisy room a short "walk" transcribed 15 s later still moves the robot | Reading | R-03 |
| 8 | A | **Router times out.** `timeout_s: 3.0`, non-streaming, `num_predict: 64`. LFM2.5-350M reaches about 30 tok/s on a Pi 5 per one vendor-style report [S, unconfirmed page]; a Pi 4 is slower. Many replies will fail and be spoken as "could not think". The schema also allows 90 characters, which at B's measured worst case of 0.78 tok/char needs about 82 tokens, so a valid reply can be cut off and parse as `none` | A `config.py:87`, `routing.py:10,31`, `adapters/router_ollama.py:20` | R-08 |
| 9 | A | **First utterance loads the model.** Whisper loads lazily on the first transcription; two workers can both load it. The first Stop after boot pays the load time, and the 8 s timeout can fire | A `stt_whisper.py:20-27` | R-09 |
| 10 | A | **Low-priority Stop blocks voice.** `A1 planner Stop then voice Move: ['stop'] ... 'a stop was just issued'`. The planner sends a Stop at the end of every walk (`robot_client.py:295`) | A `gateway.py:192,216` | R-04 |
| 11 | A | **A voice Stop can be undone.** `A2 voice Stop, planner Stop, planner Move 0.2 s later: ['stop','stop','move']`: the planner's own Stop resets the fence owner. `A3 planner Move 0.76 s after voice Stop: ['move','stop','move']`, and the planner was never told | A `gateway.py:192,216` | R-04 |
| 12 | A | **Release proof is reusable.** `A4 same frame releases a NEW E-stop 11 s later`. The gateway never sees the frame (`A5`), only a `snapshot_ok` event | A `gateway.py:258-272`, `:297-298` | R-04 |
| 13 | A | **Core 0 budget is off.** The zmq.asyncio receive path costs 212-296 us per message on Apple Silicon (500, 100 and 50 Hz runs). At A's 112 Hz and the 6-10x factor that is [E] about 14-33% of Core 0 on a Pi, against A's 1.7% row | `zmq_cost.out`; A `PLAN_04` 4.1 | R-18 |
| 14 | A | **Local control depends on a clock and a certificate.** One mTLS listener serves loopback too. The Pi has no RTC, and an expired or not-yet-valid certificate stops voice and the body, with the network healthy or not | A `mosquitto.conf:12-18`, `voice.example.yaml:4-9` | R-05 |
| 15 | A | **E-stop with no exit offline.** The latch persists across reboot, voice may not release it, and every release path needs the network (Telegram, dashboard, SSH console). With Wi-Fi down, one spoken "طوارئ" (even from a TV) leaves the robot latched until someone attaches a keyboard | A `robot.py:85-88`, `policy.py:27-35`, `PLAN_10` runbook | R-02 |
| 16 | B | **Crash forgets the E-stop.** No persistence, and `sit_and_relax` clears it (`B3 ... (False, 'sitting')`). `B2 ... jump within 60 ms of release 28.7 deg`: B leaves the E-stop ramp defect in place | B `main.py:139-140`, `robot.py:329-331` | R-01 |
| 17 | B | **Staged wake pushes before all legs are on.** The height ramp keeps running during the 0.96 s wake. `B1 height when last leg first commanded (cm): 6.78`, against a 3.5 cm sit height: late legs snap to a pose 3.3 cm lower | B `robot.py:225,329,343-353` | R-06 |
| 18 | A | **Servo slip left in.** `servos.py:194` keeps `interval * 0.999`, so A's gait has the 50-52 ms gaps with `T40` glides | Section 1.1 | R-06 |
| 19 | B | **Hallucinated motion.** The early act fires on any motion the model names. A's lexical cross-check has no equivalent | B `pipeline.py:268-272` | R-08 |
| 20 | A | **Server trouble slows every low-confidence command.** STT escalation runs before the grammar, with a 6 s timeout | A `pipeline.py:185,229-240` | R-09 |
| 21 | B | **Server-first STT costs 4 s per utterance when the server is gone.** The broker is local, so `publish` succeeds and the call waits out its timeout every time | B `rpc.py:24-26`, `config.py:59` | R-09 |
| 22 | Both | **Stand from limp at full speed.** Baseline behaviour, softened by B only. Inrush on 18 servos can brown out the rail. Both plans defer to a bench | B6, HW4 | Existing gates |
| 23 | Both | **Narrow obstacles.** At 216 scans/s and 5.55 Hz, consecutive scans are 9.25 deg apart, so a chair leg at 0.5 m (about 3 deg) is hit by roughly one scan in three. Neither plan's bench tests this; both use boards | Manual rates, [E] | R-07 |
| 24 | Both | **`#nP0` is not documented.** Whether the servos go limp, and whether a fall is really a torque-off event, is unknown. Both flag it | `servos.py:212` | Existing gates |
| 25 | A | **Mic frames arrive in bursts.** `arecord` runs with no `--period-time`, so ALSA's default period (commonly 125 ms) delays both VAD edges | A `audio.py:33-36` | R-20 |
| 26 | Both | **UVC camera keeps the USB stream open** between snapshots (`camera.py:53-61`), continuous interrupts through a controller whose affinity may not be movable | Reading; IRQ movability unconfirmed | R-20 |

**Blocking calls in the control loop:** none found in either patch. A's latch writes on a short-lived
thread (`A:safety.py:54-59`). A's 10 ms serial write timeout and `out_waiting` skip are sound.

**Races found:** B's `_speaking` flag is cleared by a killed playback while the next one runs
(`B:pipeline.py:335-353`), so the robot is briefly not deaf during its own speech; A's speech lock does
not have this. A's lazy model load (item 9).

**States with no exit:** item 15 (A). B has none, because a crash or power cycle clears everything,
which is the opposite defect (item 16).

## 4. Scores

| Criterion | A | Evidence for A | B | Evidence for B |
|---|---|---|---|---|
| Safety | 8 | Fixes E-stop ramps, latch and shutdown, finds the LiDAR blind band, requires a physical cut; loses marks for reusable release proof and a Stop fence that can be undone | 5 | Hold-off and wake rule are good, but the 28.7 deg E-stop jump and crash-forgets-E-stop remain and the LiDAR blind band is missed |
| Real-time behaviour | 8 | FIFO with `RESET_ON_FORK`, mlock, 1 ms bridge poll and corrected stop distance; servo slip left in | 7 | Slip fixed, IMU at 50 Hz, GIL interval set; bridge still polls at 5 kHz and OpenCV stays in the control process |
| Latency | 5 | Short utterances never queue, but the Whisper estimate is unsupported and a 3 s blocking router will time out | 8 | Streaming act, canned audio and honest STT figures, spoiled by the serial utterance queue |
| Coherence | 7 | `trace` runs end to end and the camera split is clean; two model paths and keys on the Pi add seams | 8 | One channel, `AskReply` cannot act, ACL tested per client; the "additive" version claim is loose |
| Failure handling | 8 | Deep FMEA, cold start and clock-step recovery; offline E-stop trap and clock-dependent local auth | 6 | Local auth survives clock loss, but a Stop can be evicted and a crash loses the E-stop |
| Security | 7 | Strict per-client ACL and firewall; reusable frame proof, model ports on the tailnet | 8 | Single-use hash-bound challenge at the gateway, no model ports, no keys on the Pi |
| Feasibility, one developer | 7 | Realistic, but more processes and a relay board to build | 8 | Fewer moving parts, explicit bench harness |
| Testability | 8 | 285 tests, 14 of 15 mutations caught; one weakened assertion | 8 | 336 tests (53 gateway functions), 14 of 15 caught; ACL contract test is the best in either plan |
| Operability | 7 | Console, jitter report, sysmon; no voice bench tool | 8 | Retained status, bench harness, deploy script that fails closed, short runbooks |
| Code correctness | 8 | All pass and the D1-D18 fixes work; lazy load race and 90-char schema against 64 tokens | 6 | All pass; Stop eviction, staged wake and E-stop path are wrong on the robot |
| Extensibility | 7 | Registry and adapters, YAML policy overrides | 8 | Protocols and factory; workers move machines with no change on the Pi |
| **Total** | **80** | | **80** | |

The tie is real and is the main finding: A is the better body and safety plan, B the better interface
and voice-latency plan. Each one's weak area is the other's strength.

## 5. Per-area merge decisions

These are mechanical instructions. "Base" means start from that patch's version of the file. "Take" means
copy that behaviour in. Anything not listed for a package comes from its base.

### 5.1 Protocol: base A, with B's messages

| File | Decision |
|---|---|
| `common/src/spider_common/protocol.py` | Base A (v3, `MIN_SOURCE_PROTOCOL = 2`, `GatewayStatus`, `HealthReport`, `VoiceTurn`, `Record*`, `trace` on commands and events). Take from B: `ConfirmAction`, `ConfirmRequest`, `ConfirmChallenge`, `AskRequest`, `AskReply`, `SttRequest`, `SttReply`, the `rpc` methods on `Topics`, `challenge` and `frame_sha256` on `EStopRelease` and `Posture`, `loop_late_hist` on `RobotState`, and `RobotEvent.kind` as a plain string. Delete A's `frame_id`, `confirmed`, `snapshot_ok`. Add `preempted`, `challenge`, `clamped` to the documented kinds |
| `common/src/spider_common/link.py` | Base A (retain, will retain, drop counter). Take from B: `username`, `password`, `reconnect_max_s` |
| `common/src/spider_common/obs.py` | A. Drop B's `telemetry.py`; keep a `service` field in `setup_logging` |
| `common/src/spider_common/health.py` (B) | Drop as a module; port its Tailscale-path and failed-unit parsers into A's `sysmon.py` |
| `common/tests` | Union: A's `test_protocol.py` and B's `test_contract.py`, `test_health.py` adapted to the merged names |

### 5.2 Body and control loop: base A

Base A for `robot.py`, `main.py`, `safety.py`, `rt.py`, `config.py`, `gait.py`, `hw/lidar.py`, `hw/servos.py`,
`hw/camera.py`, `hw/kick.py`, `camera_service.py`, `sysmon.py`, `recorder.py`, units and tests. Take from B:

| Take | From | Note |
|---|---|---|
| `min_gap = interval * 0.76` | `B:hw/servos.py` | Keep A's `out_waiting` skip and 10 ms write timeout. R-06 |
| Staged wake: `_WAKE_ORDER`, `_WAKE_TICKS_PER_LEG`, `_wake_tick`, `_staged` | `B:robot.py` | With the height and pose ramps held until every leg is on. R-06 |
| `LidarFeed._merge`, `history_clouds: 3` | `B:hw/lidar.py` | Replaces A's `_values`, `_seen`, `sector_hold_s` in `LidarProcessor.process`. Keep A's upside-down point flip. R-17 |
| `sys.setswitchinterval(cfg.gil_switch_ms / 1000)` | `B:realtime.py` | Into A's `rt.py`, default 1 ms. R-19 |
| `MqttCfg.username`, `password_file`, `reconnect_max_s` | `B:config.py` | R-05 |
| `LimitRTTIME`, `OOMScoreAdjust` | `B:spider-body.service` | Added to A's unit. R-19 |
| Low-disk stop | `B:recorder.py` `min_free` | Into A's `recorder.py`. R-21 |

### 5.3 Gateway and arbitration: base B

Base B for `gateway.py`, `main.py`, `test_gateway.py`, `test_gateway_policy.py`, `test_acl_contract.py`: hold-off, `preempted`,
per-source challenge, wake rule, status. Take from A:

| Take | From | Note |
|---|---|---|
| `SourceClock` (60 s minimum, re-baseline on a settled step) | `A:gateway.py:71-123` | Replaces `DelayTracker` |
| Late rule: a late message does not refresh liveness, and every command except Stop and E-stop is refused when late | `A:gateway.py:183-202` | Limits voice 0.5 s, remote and planner 0.75 s |
| `policy.py` with `check_order` and the YAML override | `A:policy.py` | Replaces B's `Limits`. Caps are A's values. R-15 |
| Protocol version range and re-issue as v3 | `A:gateway.py:180-182,283` | R-10 |
| Snapshot rate limit | `A:gateway.py:247-256` | |
| `clamped` notice, 10 Hz tick, 0.25 s heartbeat | `A:gateway.py:63,225-237,333-338,381` | |
| `console.py` (`spider-robotctl`) | A | Adapted to the challenge flow. A's ACL user `spider-console` kept |

Delete A's `STOP_FENCE_S`, `_stop_at`, `_stop_source`, `_frame_requests`, `_frames_seen`, `_release_refusal`.

### 5.4 Voice pipeline: base A

Base A for `pipeline.py`, `segmenter.py`, `echo.py`, `stopwords.py`, `grammar.py`, `routing.py`, `text.py`, `actions.py`, `audio.py`,
`gwclient.py`, `registry.py`, `main.py`, adapters and tests. Take from B:

| Take | From | Note |
|---|---|---|
| Streaming router with `on_act` and early `act` | `B:adapters/router.py`, `pipeline.py:264-294` | Gated by A's `cross_check`. R-08 |
| Schema `maxLength: 60`, `num_predict: 80`, `timeout_s: 10` | `B:config.py:74-78` | Keep A's `num_ctx: 512`. R-08 |
| `prepare()`: pre-render phrases, warm the router, load Whisper eagerly | `B:pipeline.py:373-385`, `adapters/stt_whisper.py:21-27` | R-09 |
| Negation guard | `B:grammar.py:20,60` | Into A's `match` |
| `rpc.py`, `adapters/stt_rpc.py`, the ask path | `B:rpc.py`, `adapters/stt_rpc.py`, `pipeline.py:297-315` | Replaces A's `openai_compat`, `stt_server`. `AskReply` is the only answer shape. R-09 |
| `short_clause` for speech while moving | `B:pipeline.py:63-64` | |
| Pre-stop with cooldown | `B:pipeline.py:164-174`, `config.py:91-93` | Merge with A's `stop_on_speech_onset` as one option, **default off**. R-14 |
| `bench.py` (`spider-voice-bench`) | B | Adapted to the merged interfaces |
| `min_rms_dbfs` gate | `B:vad.py:61` | |

Delete B's `_queue`, `_worker`, `_speaking`, `_deaf_until`, `attention.py`. Wake words: union of both lists, 8 s window.

### 5.5 Brain and server: base B

Base B for `robot_client.py`, `confirm.py`, `workers.py`, `observe.py`, `telegram.py`, `supervision/server.py`, `supervision/static/index.html`,
`service.py`, `runner.py`, `config.py`, `main.py`, `vision.py`, `test_gateway_mode.py`. B's `human=True` routing beats A's
context variable: forgetting B's flag sends at the lower priority, which fails safe; forgetting A's wrapper sends at the higher one.

Take from A: `jobs.py`, `rec2bag.py`, `test_jobs.py`, and the `/record` and `/map` handlers, because the recording format is A's. Delete
B's `aws_job.py`, A's `stt_server.py`, A's `telemetry.py`. Keep A's `test_remote_release.py` only where it still applies to the challenge flow.

Server units: B's `llama-vision.service` and `llama-planner.service` (loopback, no key) and `spider-brain.service`. `setup_server.sh`
from B with A's `llama.cpp` pin. Instance default c7i.2xlarge (B), since the job is offline.

### 5.6 LiDAR bridge: base A

`body/lidar_bridge/lidar_bridge.cpp` from A (work-mode provisioning, averaged IMU, 1 ms poll, separate recording socket), with
`IMU_DECIMATE` default 10 (B's 50 Hz) in the source and in `spider-lidar.service`. Delete B's `rawcloud`, `rawimu` topics.

### 5.7 Infra and security

| Item | Winner |
|---|---|
| `infra/local/mosquitto.conf` | B: loopback password listener plus mTLS listener. Keep B's `message_size_limit 524288`, which STT needs |
| `infra/local/acl` | B, adding A's `spider-camera`, `spider-console`, `spider-recorder`, `spider-sysmon` users, and gateway read on `camera/#`. R-05 |
| `infra/pi/mqtt_passwords.sh`, `make_local_certs.sh` (server and brain only) | B |
| `nftables` | B's rules, with A's LiDAR UDP restriction and SSH-from-LAN recovery rule |
| IRQ and CPU | Both: B's `irqaffinity=1-3` in `cmdline.txt` and A's `spider-tune.sh` (per-IRQ steering, logging, governor), A's `10-spider-cpu.conf` |
| `journald`, Wi-Fi power save, broker override | B's files |
| Unit files | A's for body, lidar, camera, recorder, sysmon, with R-12 and R-19. B's `OOMScoreAdjust` ordering on all |
| Tailscale policy | A's grants, narrowed to B's ports: drop 8080, 8081, 8090 |
| AWS worker | A's `spider-autostop.*`, `worker_setup.sh`, `budget_alarm.sh`, `Dockerfile.slam`, `run_job.sh`, `run_slam.sh`, `worker-control-policy.json` |
| Secrets table, certificate rotation | B's, because certificates no longer touch local control |
| Threat model | A's table plus B's rows: Telegram takeover residual, replay of a release, forged frame, memory poisoning |

### 5.8 Observability

Union, no second system. A's `trace` from utterance to body event; A's `health/<service>` retained with last will; B's retained `gw/status` fields (owner,
hold-off, queue delay, counters); B's `loop_late_hist` beside A's `loop_late_p99_ms`; B's JSONL trace store and dashboard panels; B's alert list with
A's rate limits; A's `--jitter-seconds` report.

### 5.9 Testing

Union of both suites, with the merged names. A's `test_safety_fixes.py` and `test_console.py`; B's `test_acl_contract.py`, `test_gateway_policy.py`, `test_gateway_mode.py`,
`test_hardening.py` where still applicable. Bench catalogue: A's RT, HW and FI tables plus B's B-V1 to B-V5, B-N1, B-F1, B-F2, B-S1, B-S2 and its 200-utterance corpus.
Keep A's rule that a failed gate stops progress.

### 5.10 Delivery

| Item | Winner |
|---|---|
| Update script | B's `deploy.sh`: reads `gw/status` and **fails closed** if it cannot. Drop A's `spider-update.sh` |
| CI | A's workflow (lock check, shell, JSON, secret scan, real bridge build), adding B's explicit Python 3.12 pin |
| Pins | A's Ollama 0.40.15 and llama.cpp v0.9.0; both plans' `uv` 0.12.17; B's SDK and Point-LIO commits |
| Milestones | A's gate order (RT1 before any motion, physical E-stop before floor walking), with B's "what breaks first" ordering in the risk register |
| Runbooks | B's format, with A's content on latch, L2 warm-up and IMU provisioning |
| Cost | B's table, with A's budget alarm script. Both sets of unit prices verified where checked |

## 6. Conflicts between the patches

| # | Conflict | A | B | Winner |
|---|---|---|---|---|
| 1 | Protocol version | v3, gateway accepts 2-3 | Stays v2, "additive" | A: the change is not compatible |
| 2 | Correlation field | `trace`, on events too | `cid`, commands only | A |
| 3 | `RobotEvent.kind` | `Literal` | Plain string | B: a Pi-first upgrade must not lose events |
| 4 | Release fields | `frame_id`, `confirmed` | `challenge`, `frame_sha256` | B |
| 5 | How the gateway knows a frame exists | `snapshot_ok` event | Hashes the frame itself | B. Works with A's camera process, which publishes to the same topic |
| 6 | Stop arbitration | 0.75 s, all other sources | 2 s, equal and lower rank, `preempted` | B |
| 7 | Caps (voice, remote, planner) | 0.08/0.5/2.0, 0.05/0.3/1.0, 0.06/0.45/1.0 | 0.10/0.6/3.0, 0.06/0.4/1.5, 0.06/0.4/1.5 | A: Move length is the real protection while voice Stop takes seconds. Config can relax after the bench |
| 8 | Voice motion defaults | 0.06 m/s, 1.5 s | 0.08 m/s, 2.0 s | A |
| 9 | Lateness filter | 60 s, re-baseline, 0.5/0.75 s | 30 s, 0.4 s | A |
| 10 | Does a late heartbeat count | No | Yes | A |
| 11 | Remote wake from limp | Allowed | Frame needed; planner never | B, plus A's tilt-known guard |
| 12 | Sector map | Per-sector hold | Minimum over 3 clouds | B: simpler, and keeps narrow obstacles between scans |
| 13 | IMU rate to Python | 100 Hz | 50 Hz | B: matches the 50 Hz tick at half the wake-ups |
| 14 | Camera | Own process | Pinned thread in the body | A: decision 3, and OpenCV leaves Core 0 |
| 15 | Broker login on the Pi | mTLS | Password on loopback | B: decision 1 |
| 16 | Vision and answers from the Pi | HTTP plus key | MQTT RPC | B: no keys on the Pi, no model ports, no action field |
| 17 | Server STT | `spider-stt` over HTTP | MQTT worker | B |
| 18 | Router call | Blocking, 3 s | Streaming, 10 s | B, with A's cross-check |
| 19 | Reply limits | 90 chars, 64 tokens | 60 chars, 80 tokens | B |
| 20 | Speech-onset stop | Off | On | A's default, B's implementation |
| 21 | Stop word list | Adds "بس", "كفايه" | Without | A, measured by V2: drop "بس" if false stops are high |
| 22 | Audio capture | `arecord` | PyAudio | A |
| 23 | Recording | `.sprec`, own socket | SPLR, `raw*` topics | A |
| 24 | Update script | Refuses when moving | Refuses unless sitting or relaxed, fails closed | B |
| 25 | Real-time default | FIFO and mlock on | Off, climb a ladder | A's default, and RT1 must also measure with them off. R-19 |
| 26 | Reconnect ceiling | 30 s | 2 s for local clients | B |
| 27 | AWS instance | c7i.4xlarge | c7i.2xlarge | B |
| 28 | Ollama and llama.cpp pins | 0.40.15, v0.9.0 | 0.32.6, b12226 | A |

## 7. Rejected ideas

| Idea | Plan | Why rejected |
|---|---|---|
| mTLS on loopback, single listener | A | Clock or certificate failure stops local control, against decision 1 |
| Boolean `confirmed` with a reusable frame id | A | Reproduced: one frame released a second, new E-stop |
| 0.75 s stop fence for all other sources | A | Blocks voice after a planner Stop, and can be undone (A1-A3) |
| Direct HTTP from Pi to model servers and cloud | A | Puts keys on the Pi and opens model ports on the tailnet |
| `spider-stt` as its own HTTP service | A | Same reason; the MQTT worker needs no port |
| Non-streaming 3 s router, 90-char schema | A | Will time out, and limits contradict each other |
| Lazy Whisper load | A | First Stop pays the load time |
| Context variable to mark planner commands | A | Forgetting it fails unsafe |
| Per-sector "swept" tracking | A | More state for less persistence than a short minimum window; based on an overstated sweep figure |
| E-stop with no persistence | B | A crash silently un-latches it |
| Camera and OpenCV inside the control process, on a pinned thread | B | Keeps the import, the memory and the C-level work in the Core 0 process |
| Single utterance worker with `deque(maxlen=2)` | B | A Stop can wait or be evicted |
| Pre-stop on by default before any bench | B | Its own top-ranked risk; ships an untested behaviour as the default |
| Protocol stays v2 | B | Not additive by its own rule R2 |
| Higher caps and longer Moves | B | Lengthens worst-case travel while voice Stop takes seconds |
| Early act with no lexical check | B | Lets a hallucination start a walk |
| Node-level `health` topic without last will | B | A dead service reads as silence; A's retained per-service topic is better |
| `isolcpus` and `nohz_full` as an easy ladder rung | Both | Stock Pi kernel does not enable `NO_HZ_FULL` |

## 8. Rulings on proposed changes to agreed decisions

| Proposal | Ruling | Evidence |
|---|---|---|
| **A P-1:** Core 0 may move to Core 3 if RT1 fails | **DEFER** | Decision 2 stands. No measurement shows Core 0 is inadequate. The cited defect is partly stale (section 2.1), and the stock kernel lacks `NO_HZ_FULL` either way, so the proposed mechanism is unavailable. `rt.cpu` may exist as config, defaulting to 0. Changing it needs a written decision change citing a failed RT1 |
| **A P-2:** Keep decision 6, add a faster path later | **ACCEPT, no change to the decision** | Transcript stop words stay. Evidence is stronger than A stated: 90.9% WER on Common Voice Arabic. Expiring Moves and the physical E-stop are the primary protection |
| **B P1:** Local Whisper should be the offline fallback | **DEFER to bench B-V1** | Decision 3 stands and the default stays local-first. Published figures support the concern but none is int8 Arabic on 3 cores. The config swap is allowed if B-V1 shows p95 above 2.5 s, and only after R-09's circuit breaker exists |
| **B P2:** `kimi-k3.1-pro` has no API | **ACCEPT as a fact update** | NVIDIA page updated 2026-11-04. `moonshotai/kimi-k3` is hosted with image input under trial terms. Not a decision change: the architecture already marks the endpoint unconfirmed |
| B: speech-onset pre-stop "adds to decision 6" | **ACCEPT as an option, default off** | Consistent with decision 6. Off until the bench gate in R-14 passes |
| B: `irqaffinity=1-3` note on decision 2 | **ACCEPT** | Supports the decision; RT1 verifies what actually moves |

## 9. Binding required changes

The merged plan must apply every item below. BLOCKING items must be closed before the judge signs off. Each check must
actually be run, or, where it needs the robot, written into the plan as a gate with that pass condition.

### BLOCKING

| ID | Defect | What must change | Check that proves it |
|---|---|---|---|
| **R-01** | B leaves the E-stop defects in place: ramps run under E-stop (`B:robot.py:329-331`, 28.7 deg jump reproduced), SIGTERM clears the latch (`B:main.py:139-140`), and the latch does not survive a restart | Merged body uses A's E-stop path: `_hold_ramps`, ramp freeze in `tick`, `EStopLatch`, `_cold_estop`, guarded `sit_and_relax` | A's `test_estop_freezes_body_pose_ramp`, `test_shutdown_under_estop_does_not_move_or_clear_the_latch`, `test_latch_survives_restart_and_cold_process_sends_nothing` pass. `repro_baseline.py` A-D2 to A-D5 show no servo change, no jump, latch kept |
| **R-02** | A's persistent latch has no exit with the network down: voice may not release (`A:policy.py:27-35`), and every release path needs the network (section 3, item 15) | Add a release path needing no network: a hold-to-release button on GPIO (3 s press), in the M4 hardware list, through a new gateway source allowed only `estop_release`, ACL-bound to its own client. Refused while any motion source owns the robot. Add the runbook. Voice release stays forbidden | Unit tests: 3 s hold releases, short press does not, and the source cannot send motion. Bench gate with Wi-Fi off: latch, reboot, release by button only. Until M4, the plan states this limitation |
| **R-03** | B can lose or delay a Stop (`B:pipeline.py:103,177-181,420-429`; output: 0 stop commands). A has an unbounded short-utterance backlog with no age check (`A:pipeline.py:120-128`), so old speech can move the robot | Use A's concurrent short-utterance dispatch. Never drop or queue a stop-word check behind another utterance's STT beyond the worker pool. Bound the backlog. A motion act is discarded when `now - utterance end > max_motion_age_s` (default 6.0 s, set by V1); Stop and E-stop are never discarded | New tests with a slow fake STT: a Stop among 6 segments always reaches the gateway; a motion transcript older than the limit sends nothing. B5 and B6 attack scripts, adapted to the merged pipeline, show the Stop sent |
| **R-04** | A's gateway allows reuse of a release frame (A4), a low-priority Stop to block voice (A1), and a voice Stop to be undone (A2, A3). `A:gateway.py:192,216,258-272` | Base gateway on B: rank-based hold-off, `preempted`, single-use `challenge` bound to `frame_sha256`, source and action. Remove A's fence and frame bookkeeping (section 5.3) | B's `test_voice_stop_is_not_undone_by_the_next_planner_renewal`, `test_challenge_is_single_use`, `test_challenge_expires` pass. `attack_a.py` against the merged gateway: A1 sends the voice Move, A2 and A3 send no Move, A4 does not release twice |
| **R-05** | A runs local clients over mTLS (`A:mosquitto.conf:12-18`), so a wrong clock or expired certificate stops the body, gateway and voice, against decision 1 | B's two listeners and per-process passwords. Merged ACL covers every client of both plans (`spider-camera`, `spider-console`, `spider-recorder`, `spider-sysmon`, gateway read of `camera/#` and `state`) | `test_acl_contract.py` extended to all merged clients. Gate at M1 on the real broker: with the Pi clock set to 2000-01-01 all local clients connect and a Stop reaches the body; every forbidden publish refused (NET5) |
| **R-06** | Servo timing and wake: A keeps the group-move slip (`A:hw/servos.py`, 0.999 factor; 55-62% of gaps over 45 ms). B's staged wake runs the height ramp while legs are still limp (6.78 cm at last leg, against a 3.5 cm sit height; `B:robot.py:225,329,343-353`) | Take B's `min_gap` into A's bank, keeping A's `out_waiting` skip. Take B's staged wake and hold height and body-pose ramps until every leg has been commanded | `test_ssc_keeps_25_hz_under_tick_jitter` passes. New test: during staged wake `gait.height == sit_height_m` and every leg's first command is the sit pose; the ramp starts only after the last leg. Bench B1 logic-analyser gate: no gap over 45 ms |
| **R-07** | LiDAR commissioning and blind band. B has no IMU provisioning, and neither plan handles the manual's "IMU Disable" factory default with a defined check. B misses the low-obstacle blind band entirely. Neither tests narrow obstacles or the warm-up | Merged plan keeps A's provisioning and H-02, and adds: (a) a commissioning step that sets the IMU enable bit and an explicit NEGA choice, then verifies IMU data; (b) a hazard row and an operating rule for low objects, including that in normal mode nothing below the sensor plane is seen; (c) L2 warm-up in the runbook and the FMEA | Bench gate HW1: `roll_deg` non-null after provisioning; `stand` accepted; a 5 cm box and a 2.5 cm pipe at 0.5 m, in at least 8 bearings, each either stop the robot or are recorded as not visible, with the mount decision following from the result; time from cold power-on to first cloud recorded |
| **R-08** | Router: A times out and its limits contradict (`A:config.py:87`, `A:routing.py:10,31`). B's early act has no lexical check (`B:pipeline.py:268-272`) | Streaming with early `act` from B, `maxLength: 60`, `num_predict: 80`, `timeout_s: 10`, `num_ctx: 512` from A. `cross_check` runs on the transcript before the early act dispatches and again on the final act | New test: a stream naming `forward` for a transcript with no motion word sends no Move. Existing router tests pass. Bench S1: at least 98% valid JSON and no truncation |
| **R-09** | STT chain. A escalates before the grammar (`A:pipeline.py:185`) and loads Whisper lazily with a race (`A:stt_whisper.py:20-27`). B's RPC waits its full timeout each utterance when the server is gone (`B:rpc.py:24-26`) | Grammar before any escalation. A circuit breaker on the server path: after a timeout, skip it for 30 s. Eager single Whisper load and router warm-up before the service reports ready | New tests: a grammar hit with low confidence makes no server call; with a hanging server the second utterance does not wait; the model constructor runs exactly once before the first utterance. Bench B-F1 shows voice ready with the server off |
| **R-10** | Two incompatible contracts (section 6, rows 1-5) | One `protocol.py` as in section 5.1. A's v3 and accepted range, `trace`, `kind` as a string, B's challenge fields and RPC messages | Merged `test_protocol.py` and `test_contract.py` pass. A v2 Move is accepted and re-issued as v3. An unknown event kind is parsed by an old-style reader without error |
| **R-11** | A's voice latency targets rest on an unsupported figure (`PLAN_01` L-02, L-07, L-09, L-11; `PLAN_04` 4.6; `PLAN_00`) and state that no published figure exists | Restate local STT as [E] 3-8 s with the sources in section 2.1, offline voice Stop as [E] 3.3-8.3 s to braking, and the online path as [E] 1.3-2.4 s. State WER as 63.4% and 90.9%. Do not present voice Stop as a fast path | `01_SYSTEM_DESIGN.md` shows these figures and labels, and names bench V1 as the replacement. `00_REPORT.md` top risks say so plainly |
| **R-12** | Both plans keep `After=network-online.target` on safety-relevant units, and Debian's Mosquitto unit has it too (section 3, item 1), against decision 1 | Remove it from `spider-body`, `spider-gateway`, `spider-lidar` and `spider-voice`; order them only on local units. Override Mosquitto to start without it | Gate on the Pi with Wi-Fi off: `systemd-analyze critical-chain spider-body.service` shows no wait on `network-online.target`; voice ready within the 90 s target |
| **R-13** | Limp at startup is the only fix in either plan no test catches (section 1.2) | Add a regression test: `run()` calls `servos.relax()` before the first tick when not latched and does not when latched | With that call removed, the test fails. Re-run the mutation |

### NON-BLOCKING

| ID | Defect | What must change | Check |
|---|---|---|---|
| R-14 | B's pre-stop is on by default (`B:config.py:92`) | One option, default off. Bench gate: walking in a quiet room, at most 1 false stop per 5 minutes before enabling | Config default false; gate written |
| R-15 | Caps differ | A's values, in `policy.py`, overridable by file, checked by `check_order` | `test_remote_speed_and_duration_are_capped` |
| R-16 | A's Stop during a ramp leaves a mid-height robot that may then walk or relax (`A:robot.py:191-194`, `:205-211`, `:225`) | Refuse Moves unless at standing height within a tolerance, and `relax` unless at sit height | New test for both |
| R-17 | A's "166 deg per cloud" is overstated | Correct ADR-11, the `config.py` comment and D1. Use B's merge | HW1 logs an azimuth histogram per cloud |
| R-18 | A's Core 0 budget is about ten times low for ZeroMQ wake-ups | Use the measured path cost, `IMU_DECIMATE=10`. First ladder rung if RT1 fails: drain the socket with `NOBLOCK` inside the tick, before any kernel change. Rewrite `isolcpus` and `nohz_full` rungs: the stock kernel has no `NO_HZ_FULL` | Budget table; RT1 reports Core 0 load |
| R-19 | A lacks the GIL interval and FIFO runaway guard; B ships FIFO off | `setswitchinterval(1 ms)`, `LimitRTTIME`. RT1 is run with FIFO and mlock off, then on, and the gate is judged on the shipped setting | Both results in `06_VALIDATION.md` after the bench |
| R-20 | `arecord` default periods; UVC stream left open | `--period-time=20000 --buffer-time=80000`; close the V4L2 stream between snapshots, or measure and record the interrupt rate | V4 onset timing; `/proc/interrupts` diff during RT1 |
| R-21 | A's recorder can fill the disk, and a latch write failure only logs (`A:safety.py:86-87`) | B's low-disk stop; emit an `error` event when the latch cannot be persisted | Tests for both |
| R-22 | `A:brain/tests/test_robot_source.py:24` weakened to a subset | Assert the remote topic is present and the set is a subset | Test fails when nothing is sent |
| R-23 | B's pins are stale | Ollama 0.40.15, llama.cpp v0.9.0 | M2 runs LFM2.5-350M on the pinned Ollama |
| R-24 | Whisper window cost is unknown | Add to V1: measure `chunk_length` if faster-whisper accepts it for short windows; otherwise record the fixed-window cost, and whether a `whisper.cpp` adapter with a short `audio_ctx` is worth adding | Result in `06_VALIDATION.md` |
| R-25 | B's serial `_speaking` race, if any of that code is kept | Do not keep it; A's lock stays | Reading in the second round |

## 10. Unresolved items

Everything below is **not verified by me**. Each needs the named hardware or test.

| Item | Why not verified | Replaced by |
|---|---|---|
| Real Mosquitto loading either config or ACL | Not installed here. I did not run a build tool on a downloaded archive. mosquitto.conf(5) confirms the option semantics only | M1 gate, NET5 |
| Anything on a Pi 4: tick timing, jitter, IRQ movability, FIFO behaviour, thermals, boot time with no network | No hardware, by rule | RT1, HW5, B-F1 |
| Whisper tiny int8 Arabic latency on 3 cores | No direct published figure exists; the sources are nearby setups | V1, B-V1 |
| LFM2.5-350M speed on a Pi 4, JSON validity, Arabic quality | Not run. The 30 tok/s Pi 5 figure comes from a search result, and its source page returned 404 when fetched | S1, B-V2 |
| Ollama loading the LFM2.5-VL projector | Liquid's pages conflict and do not settle it. `llama-server` remains the decision | V6 |
| Two-sided L2 scan geometry | Inferred from the manual's wording | HW1 azimuth histogram |
| L2 factory defaults for the IMU and NEGA | The manual and README disagree, and the manual disagrees with itself | HW1 |
| `#nP0` on the SSC-32U and RDS3218 limp behaviour | Not documented | HW2, B6 |
| Servo stall current, brown-out, relay rating | No hardware | HW4 |
| Speech-onset false-stop rate near servos | No hardware | V4, B-V4 |
| Tailscale relay behaviour on this link | Published figures are anecdotal | NET2, B-N1 |
| Point-LIO on hexapod motion | Needs a real recording | M7 |
| NIM trial limits, AWS scripts | No accounts, by rule | M6, M7 |
| Arabic token budgets | Both planners measured them with the real tokenizer and agree in order of magnitude; I did not re-run them | S1 |
| B's Home Assistant 5-6 s report; SSC-32U guide page references; existence of tag `b12226` | Not fetched | Not decision-critical |
| Time for `network-online.target` to time out on Pi OS | Depends on the image | R-12 gate |

**Harness note:** my first test run captured exit codes with a shell variable that zsh does not set, so the exit-status lines in
the raw files are blank. The pass counts come from pytest's own summary lines and are the evidence used.
