# Spider robot: judge's verdict

Written for the owner and for anyone reviewing the design. The judge's own words follow, unedited, from
its two rounds; only the headings are nested. Full reports: `_work/judge/JUDGE_ROUND_1.md` and
`JUDGE_ROUND_2.md`. Nothing either round did touched real hardware.

## Summary

| | Result |
|---|---|
| Round 1 scores, separate plans | Plan A 80, Plan B 80, of 110. A won body and safety, B won interfaces and voice latency |
| Round 1 required changes | 13 BLOCKING, 12 NON-BLOCKING. All 25 closed in the merged plan, confirmed by the judge in round 2 |
| Round 2 scores, merged plan | **84 of 110**, before the fixes in the next row |
| Round 2 new findings | 8 BLOCKING, 7 NON-BLOCKING, in the path from the Mac to the robot and in the Whisper timeout |
| After round 2 | The lead fixed all 8 BLOCKING and 6 of the 7 NON-BLOCKING. **The process limits review to two rounds, so the judge has not re-checked these fixes.** Evidence is below |

## Lead's closure of the round 2 findings (not reviewed by the judge)

| ID | Severity | What was done | Evidence |
|---|---|---|---|
| J2-01 | BLOCKING | The TLS listener moved to `infra/local/mosquitto-tls.conf`, installed last by P03, which also says how to remove it. ADR-12 corrected | **Unverified on a real broker**: Mosquitto is not available here. Gate NET5 |
| J2-02 | BLOCKING | `setup_pi.sh` uses `sudo install -o spider` | `bash -n` only |
| J2-03 | BLOCKING | P05 stops `spider-lidar` first and provisions as `spider` on a separate endpoint | Text; needs the Pi |
| J2-04 | BLOCKING | P06 is a HUMAN STEP | Text |
| J2-05 | BLOCKING | `bench` gateway source, off unless `SG_BENCH=1`, capped at 0.12 m/s, ACL-bound to the console. Exact commands in P08 and P09. `SG_BENCH=0` restored at the end of P09 | 5 gateway tests, 2 console tests, ACL contract tests |
| J2-06 | BLOCKING | `/usr/local/bin/spider-robotctl` wrapper runs as `spider` with `gateway.env`; console default port 1883 | `bash -n`; needs the Pi |
| J2-07 | BLOCKING | Timeout 20 s, set from V1. `TranscribeTimeout` keeps the slot until the thread ends. Three timeouts in a row: `degraded` and an alert | `test_a_timed_out_transcription_*`, `test_whisper_timeout_*`, `test_repeated_speech_timeouts_*` |
| J2-08 | BLOCKING | Index generated from the step markers, with an assertion in the generator | Independent check: 39 rows, 0 wrong |
| J2-09 | NON-BLOCKING | **Open.** One lateness clock per source. A runbook note says to stop the brain if skew exceeds 0.75 s | Keying by session would weaken lateness across restarts |
| J2-10 | NON-BLOCKING | Newest short utterance served first | `test_a_stop_arriving_last_*` |
| J2-11 | NON-BLOCKING | Full `spider-calibrate` commands; RT1 in `tmux`; P07 wording | Text |
| J2-12 | NON-BLOCKING | Two tests added | Both mutations now caught, run by the lead |
| J2-13 | NON-BLOCKING | Q02 sets `server_tailscale_name` | Text |
| J2-14 | NON-BLOCKING | Text aligned | Text |
| J2-15 | NON-BLOCKING | Limit stated in section 10 of the design | Text |

## Final scores for the merged plan (round 2)

| Criterion | Score | Evidence |
|---|---|---|
| Safety | 8 | E-stop path and hold-off proven by mutation; physical E-stop and low-obstacle mount are gates, not yet facts; P06 starts the body |
| Real-time behaviour | 8 | FIFO with `RESET_ON_FORK`, GIL interval, servo cadence fixed, measured budget; RT1 still unrun |
| Latency | 7 | Grammar first, streaming act, canned audio; Whisper [E] 3-8 s and an 8 s timeout at the top of that range |
| Coherence | 8 | One protocol, ACL matches every client's real topics; two clients share one lateness clock |
| Failure handling | 7 | Latch, button, breaker and gateway rules hold; broker certificate coupling and the STT timeout are the gaps |
| Security | 8 | Single-use bound challenge, loopback passwords, no model ports or cloud keys on the Pi |
| Feasibility, one developer | 7 | Sound build order, reproducible code delivery; several P steps fail as written |
| Testability | 9 | 469 tests, 36 of 38 mutations caught, plan blocks hash-verified, full bench catalogue |
| Operability | 6 | Retained status, bench tool, runbooks; fallback console and M3/M4 commands do not work as written |
| Code correctness | 8 | Every attack passes; the one real defect is the Whisper timeout path |
| Extensibility | 8 | Protocol, policy file, adapters, MQTT workers |
| **Total** | **84 / 110** | |

## Round 1 scores

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

## Merge decisions

These are mechanical instructions. "Base" means start from that patch's version of the file. "Take" means
copy that behaviour in. Anything not listed for a package comes from its base.

#### 5.1 Protocol: base A, with B's messages

| File | Decision |
|---|---|
| `common/src/spider_common/protocol.py` | Base A (v3, `MIN_SOURCE_PROTOCOL = 2`, `GatewayStatus`, `HealthReport`, `VoiceTurn`, `Record*`, `trace` on commands and events). Take from B: `ConfirmAction`, `ConfirmRequest`, `ConfirmChallenge`, `AskRequest`, `AskReply`, `SttRequest`, `SttReply`, the `rpc` methods on `Topics`, `challenge` and `frame_sha256` on `EStopRelease` and `Posture`, `loop_late_hist` on `RobotState`, and `RobotEvent.kind` as a plain string. Delete A's `frame_id`, `confirmed`, `snapshot_ok`. Add `preempted`, `challenge`, `clamped` to the documented kinds |
| `common/src/spider_common/link.py` | Base A (retain, will retain, drop counter). Take from B: `username`, `password`, `reconnect_max_s` |
| `common/src/spider_common/obs.py` | A. Drop B's `telemetry.py`; keep a `service` field in `setup_logging` |
| `common/src/spider_common/health.py` (B) | Drop as a module; port its Tailscale-path and failed-unit parsers into A's `sysmon.py` |
| `common/tests` | Union: A's `test_protocol.py` and B's `test_contract.py`, `test_health.py` adapted to the merged names |

#### 5.2 Body and control loop: base A

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

#### 5.3 Gateway and arbitration: base B

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

#### 5.4 Voice pipeline: base A

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

#### 5.5 Brain and server: base B

Base B for `robot_client.py`, `confirm.py`, `workers.py`, `observe.py`, `telegram.py`, `supervision/server.py`, `supervision/static/index.html`,
`service.py`, `runner.py`, `config.py`, `main.py`, `vision.py`, `test_gateway_mode.py`. B's `human=True` routing beats A's
context variable: forgetting B's flag sends at the lower priority, which fails safe; forgetting A's wrapper sends at the higher one.

Take from A: `jobs.py`, `rec2bag.py`, `test_jobs.py`, and the `/record` and `/map` handlers, because the recording format is A's. Delete
B's `aws_job.py`, A's `stt_server.py`, A's `telemetry.py`. Keep A's `test_remote_release.py` only where it still applies to the challenge flow.

Server units: B's `llama-vision.service` and `llama-planner.service` (loopback, no key) and `spider-brain.service`. `setup_server.sh`
from B with A's `llama.cpp` pin. Instance default c7i.2xlarge (B), since the job is offline.

#### 5.6 LiDAR bridge: base A

`body/lidar_bridge/lidar_bridge.cpp` from A (work-mode provisioning, averaged IMU, 1 ms poll, separate recording socket), with
`IMU_DECIMATE` default 10 (B's 50 Hz) in the source and in `spider-lidar.service`. Delete B's `rawcloud`, `rawimu` topics.

#### 5.7 Infra and security

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

#### 5.8 Observability

Union, no second system. A's `trace` from utterance to body event; A's `health/<service>` retained with last will; B's retained `gw/status` fields (owner,
hold-off, queue delay, counters); B's `loop_late_hist` beside A's `loop_late_p99_ms`; B's JSONL trace store and dashboard panels; B's alert list with
A's rate limits; A's `--jitter-seconds` report.

#### 5.9 Testing

Union of both suites, with the merged names. A's `test_safety_fixes.py` and `test_console.py`; B's `test_acl_contract.py`, `test_gateway_policy.py`, `test_gateway_mode.py`,
`test_hardening.py` where still applicable. Bench catalogue: A's RT, HW and FI tables plus B's B-V1 to B-V5, B-N1, B-F1, B-F2, B-S1, B-S2 and its 200-utterance corpus.
Keep A's rule that a failed gate stops progress.

#### 5.10 Delivery

| Item | Winner |
|---|---|
| Update script | B's `deploy.sh`: reads `gw/status` and **fails closed** if it cannot. Drop A's `spider-update.sh` |
| CI | A's workflow (lock check, shell, JSON, secret scan, real bridge build), adding B's explicit Python 3.12 pin |
| Pins | A's Ollama 0.40.15 and llama.cpp v0.9.0; both plans' `uv` 0.12.17; B's SDK and Point-LIO commits |
| Milestones | A's gate order (RT1 before any motion, physical E-stop before floor walking), with B's "what breaks first" ordering in the risk register |
| Runbooks | B's format, with A's content on latch, L2 warm-up and IMU provisioning |
| Cost | B's table, with A's budget alarm script. Both sets of unit prices verified where checked |

## Conflicts between the plans

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

## Rejected ideas

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

## Rulings on proposed changes to agreed decisions

| Proposal | Ruling | Evidence |
|---|---|---|
| **A P-1:** Core 0 may move to Core 3 if RT1 fails | **DEFER** | Decision 2 stands. No measurement shows Core 0 is inadequate. The cited defect is partly stale (section 2.1), and the stock kernel lacks `NO_HZ_FULL` either way, so the proposed mechanism is unavailable. `rt.cpu` may exist as config, defaulting to 0. Changing it needs a written decision change citing a failed RT1 |
| **A P-2:** Keep decision 6, add a faster path later | **ACCEPT, no change to the decision** | Transcript stop words stay. Evidence is stronger than A stated: 90.9% WER on Common Voice Arabic. Expiring Moves and the physical E-stop are the primary protection |
| **B P1:** Local Whisper should be the offline fallback | **DEFER to bench B-V1** | Decision 3 stands and the default stays local-first. Published figures support the concern but none is int8 Arabic on 3 cores. The config swap is allowed if B-V1 shows p95 above 2.5 s, and only after R-09's circuit breaker exists |
| **B P2:** `kimi-k3.1-pro` has no API | **ACCEPT as a fact update** | NVIDIA page updated 2026-11-04. `moonshotai/kimi-k3` is hosted with image input under trial terms. Not a decision change: the architecture already marks the endpoint unconfirmed |
| B: speech-onset pre-stop "adds to decision 6" | **ACCEPT as an option, default off** | Consistent with decision 6. Off until the bench gate in R-14 passes |
| B: `irqaffinity=1-3` note on decision 2 | **ACCEPT** | Supports the decision; RT1 verifies what actually moves |

## Binding required changes, round 1

The merged plan must apply every item below. BLOCKING items must be closed before the judge signs off. Each check must
actually be run, or, where it needs the robot, written into the plan as a gate with that pass condition.

#### BLOCKING

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

#### NON-BLOCKING

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

## Round 2 closure of round 1 items

| ID | Status | Evidence |
|---|---|---|
| R-01 | **Closed** | `robot.py:167` `_hold_ramps`; `:366` ramps frozen under E-stop; `:91` cold estop from latch; `safety.py` `EStopLatch`; `main.py` guarded `sit_and_relax`. Mutations caught; B2, B3 above |
| R-02 | **Closed** | `button.py:34-51,80-97`; `gateway.py:271-284` (release only, stale refused, refused while owned); ACL `spider-button`; design §6.6 states the pre-M4 limit. Mutations caught |
| R-03 | **Closed in code, with J2-07 and J2-12 open** | `pipeline.py:149-176` FIFO shorts, bounded at 8, long never takes the last worker; `:186-188,243-246,260` age limit; Stop exempt `:294-312`. Attack B5/B6 scenario no longer applies |
| R-04 | **Closed** | `gateway.py:286-298` rank hold-off and `preempted`; `:412-421` single-use, hash, expiry; A1-A4 above |
| R-05 | **Closed for the normal case; J2-01 is the remaining gap** | `mosquitto.conf:19-26` two listeners; ACL covers all clients, confirmed statically against each client's real topics and wills (section 3.3). Real broker not run |
| R-06 | **Closed** | `hw/servos.py` `min_gap` 0.76 with `out_waiting` skip; `robot.py:366,393-396` ramps held during wake; B1 above; mutations caught |
| R-07 | **Closed in design; P05 as written is broken (J2-03)** | P05 step, H-02, FMEA S4, runbook |
| R-08 | **Closed** | `routing.py:10,31-33` 60 chars, 80 tokens, `num_ctx` 512; `router_ollama.py` streaming; `pipeline.py:258-267` `cross_check` before the early act and on the final act; mutations caught |
| R-09 | **Closed** | `pipeline.py:234-241` grammar first; `stt_rpc.py:32-44` 30 s breaker; `stt_whisper.py:18` eager load; mutations caught |
| R-10 | **Closed** | `protocol.py:23-24` v3, range; `:92,221` `trace`; `:218` `kind` string; `:142-143` challenge fields. A word-boundary search finds no `cid` left in code **[V]** |
| R-11 | **Closed** | Design L-02, L-09, L-11, sections 4.6, 12 |
| R-12 | **Closed in unit files; gate B-F1 pending** | Body, lidar, gateway, voice, button, camera, recorder, sysmon units order on local units only; `mosquitto.service`, `ollama.service` replaced whole. The claim that a drop-in cannot remove `After=` is correct per systemd.unit(5) |
| R-13 | **Closed** | Tests named in section 1.1, both mutations caught |

**R-14 to R-25: all closed in code or documents** ([V] by search: `stop_on_speech_onset` default false;
`policy.py`; `_at_height`; `_merge` and upside-down flip; `set_gil_interval`, `LimitRTTIME`;
`--period-time=20000 --buffer-time=80000`; `min_free_bytes`, `write_failed`; `test_robot_source.py:25-26`;
pins; V1 note). R-24 stands only as text in P10 until the bench runs.

#### Changes beyond the list

| Change | Verdict |
|---|---|
| `cross_check` refuses a negated motion | **Sound.** Tested; only rejects, so a false hit is safe |
| `امشي`, `تقدم`, `ارجع` in the lexicon | **Sound, watch one thing.** `تقدم` is 4 letters, so `قدم` ("foot" or "come") is one edit away and matches as forward. Needs the wake gate, so low risk; V2 false-motion test covers it |
| Long utterance waits in a one-slot pending position | **Sound.** Better than dropping a stop word inside it |
| `stt.primary: whisper_server` and `ServerFirstSTT` | **Sound.** Off by default, breaker exists |
| `HealthReport.info` | **Sound.** Keys match `observe.assess` and `sysmon` |
| `drain()` yields once per loop | **Sound** |
| `apply_step.py` with SHA-256 | **Sound and verified** (section 1); the search-and-replace blocks match exactly once |
| No server health reporter | **Accepted**; stated in design section 8 |

## Round 2 findings as written by the judge

Severity BLOCKING means the plan cannot be handed to the executor until fixed.

| ID | Severity | Defect | Fix | Check that proves it |
|---|---|---|---|---|
| **J2-01** | **BLOCKING** | `infra/local/mosquitto.conf:21-26` names certificates that do not exist until P03, but `setup_pi.sh:87,114` installs that file and restarts the broker in P02. Mosquitto exits when a listener's certfile is missing **[E, source knowledge; no real broker here]**, so `systemctl restart` fails, `set -e` aborts P02 before "Installed", and P02's stop condition fires. It also contradicts ADR-12 and section 7: a missing or bad server certificate takes loopback down with it, so "certificate problems cannot affect local control" is false | Move the 8883 listener to `/etc/mosquitto/conf.d/spider-tls.conf`, installed only by P03 after the files exist. Correct ADR-12 and section 7 to say the listener is added last and a bad cert stops the whole broker | On a fresh Pi image: `setup_pi.sh` exits 0 with no certs and `systemctl is-active mosquitto` is `active`; loopback ACL test passes before P03; 8883 listens only after P03. Text check on ADR-12 |
| **J2-02** | **BLOCKING** | `setup_pi.sh:104-106` run `sudo -u spider cp` and `sudo -u spider install` from `$SR`, which is under the installing user's home. Debian 12 `adduser` defaults to DIR_MODE 0700 **[S]**; Pi OS confirmation pending. If so, spider cannot read the source and `set -e` aborts P02 | `sudo install -o spider -g spider -m <mode> "$SR/..." /etc/spider/...`, as the rest of the script already does | `setup_pi.sh` from a 0700 home on the Pi exits 0; `/etc/spider/robot.yaml` owned by spider |
| **J2-03** | **BLOCKING** | P05 step 2 runs `sudo LIDAR_SET_WORK_MODE=... lidar_bridge` while `spider-lidar` is already running (enabled at P02). The bridge binds ZeroMQ first (`lidar_bridge.cpp:75-90`), then exits at `:107` without closing it. Running as root over the service's socket path removes it and leaves a root-owned `/tmp/spider_lidar.ipc`, which the `spider` user cannot unlink in sticky `/tmp`, so the service cannot bind afterwards until reboot **[E, from libzmq's bind behaviour]** | P05: `sudo systemctl stop spider-lidar` first. Run with `ZMQ_ENDPOINT=ipc:///tmp/spider_provision.ipc ZMQ_RECORD_ENDPOINT=` and as user `spider`. Better: do the work-mode branch before any `zmq_bind` and call `zmq_close` on exit | On the Pi: provision, `systemctl start spider-lidar`, `is-active` is `active` and `roll_deg` is non-null |
| **J2-04** | **BLOCKING** | P06 is an executor step, but `bench_jitter.sh:13-14,17-19` stops and starts `spider-body` (the `trap` starts it on exit). Executor rule 12 forbids exactly this: "Starting `spider-body` ... is always a HUMAN STEP". The only guard is a precondition the executor cannot verify | Make P06 a HUMAN STEP that the owner runs after confirming servo power is off, or remove the `trap` and have the owner confirm first. Either way, no executor-run command starts the body | Reading P06 and the script: no executor-run command starts the body |
| **J2-05** | **BLOCKING** | Between P07 and P10 nothing can stand or move the robot. `console.py:161` offers only status, stop, estop, release; voice is enabled in P10 and the brain in Q02. P08 steps 4-6 and P09 (RT2, B1, B6, RT3) cannot run. RT3 also asks for 0.12 m/s while the highest gateway cap is 0.08 (`policy.py:27-35`) | Add a bench path: `spider-robotctl bench stand\|sit\|relax\|walk` through a dedicated source `bench`, off unless `SG_BENCH=1`, ACL-bound to `spider-console`, policy capped at 0.12 m/s. Write the exact commands into P08 and P09 | Tests: `bench` refused when off, cap enforced, end to end through gateway and simulated body. P08/P09 name each command; `rg` shows no undefined command |
| **J2-06** | **BLOCKING** | The SSH fallback (agreed decision 8) cannot run as documented. `spider-robotctl` is not on PATH; `console.py:118-123` reads `SC_*` only from the environment and defaults to port 1884 (the simulator's); `/etc/spider/secrets` is mode 750 spider. A person typing `spider-robotctl status` over SSH gets a timeout | Install `/usr/local/bin/spider-robotctl` that runs as `spider` with `gateway.env` loaded, and default the port to 1883. Runbook and P08 use it | `spider-robotctl status` from the SSH user on the Pi prints mode; `bash -n` on the wrapper |
| **J2-07** | **BLOCKING** | `voice/config.py:46` `timeout_s: 8.0` is the top of the plan's own [E] 3-8 s, and two overlapping transcriptions share three cores, so timeouts are likely under exactly the load where a Stop matters. `stt_whisper.py:48` abandons the thread on timeout, and `pipeline.py:204-206` releases the slot at once, so the scheduler sees free workers that are not. Reproduced in a scaled test: all three calls timed out and a pool thread was still running. A slow Pi loses every voice command, Stop included, with `spider-voice` still "ok". This also contradicts FMEA P10 ("the worker frees") | Default `timeout_s` to at least 20 s, set from V1 in P10. Release the slot when the thread ends, not at the timeout. Raise a `degraded` health state and an alert on repeated STT timeouts | New test: with a model slower than the old limit and the new default, a Stop is transcribed; `_stt_running` stays honest while abandoned threads run; health goes `degraded` after N timeouts |
| **J2-08** | **BLOCKING** | `04_EXECUTION_PLAN.md:36-73`: the index gives wrong line ranges for 38 of 39 steps, because they were computed before the file blocks were embedded. Example: S21 is listed at 3013-3187 and is really at 14880-15449. Rule 7 tells the executor to read by those ranges | Regenerate the index from the `BEGIN-STEP` and `END-STEP` markers, and add a checker | `python3` check: every `\| Sxx \| ... \| a-b \|` equals the marker lines |
| J2-09 | NON-BLOCKING | `gateway.py:189,236`: one `SourceClock` per source mixes the brain's clock and the console's on `remote`. With skew over 0.75 s the console's commands are refused as late (reproduced). Stops still pass | Key the clock by source and session, or give the console its own source | Test: both clients on `remote` with a 2 s skew are accepted |
| J2-10 | NON-BLOCKING | Under sustained chatter the FIFO short queue can make a Stop wait up to about 20 s or be evicted (`pipeline.py:150-154`). Stop is not the primary protection, but it is unnecessary | Serve the newest short utterance first, since older ones are discarded by the age limit anyway | Test: a Stop arriving last with a full queue is transcribed next. V2 noisy runs |
| J2-11 | NON-BLOCKING | P08 calls `spider-calibrate` with a default of `config/robot.yaml` (`calibrate.py:100`), which does not exist on the Pi, and no full path. P06's two 1-hour runs will exceed an ordinary agent's command timeout. P07 says "commands above" with the commands below it | Give full commands with `--config /etc/spider/robot.yaml`; run RT1 under `systemd-run --unit` or `tmux`; reorder P07 | Reading the steps |
| J2-12 | NON-BLOCKING | Two R-03 behaviours have no test (section 1.1) | Add a stale early-act test and a "long never takes the last worker" test | Both mutations caught |
| J2-13 | NON-BLOCKING | `sysmon.server_tailscale_name` is never set by any step, so the "no Tailscale path" alert is inert | Set it in P01 or P04 | `health/system` carries `tailscale_path` |
| J2-14 | NON-BLOCKING | Doc mismatches: L-09's 3.4-8.4 s against `max_motion_age_s` 6.0, which discards anything older; sysmon 64 MB in design against 96 MB in its unit; server key 600 in the secrets table against 640 in P03; "nine small processes" against ten | Align the text | Reading |
| J2-15 | NON-BLOCKING | `deploy.sh` does not refresh ACL, units or bridge, and restarts `spider-button` and `spider-voice` even if never enabled. The plan never runs it | State the limit in section 10, or install units and ACL in the release step | Reading |

## Contract and permissions check, round 2

#### 3.3 Contract check across packages [V, static]

Real topics and last wills, read from each client's own code, against `infra/local/acl`:

| Client | Subscribes | Publishes | Last will | Result |
|---|---|---|---|---|
| body | `cmd` | `state`, `event`, `camera/*` | `event` | ok |
| gateway | `gw/+/cmd`, `event`, `state`, `camera/+` | `cmd`, `gw/+/event`, `gw/status` | `gw/status` (retained) | ok |
| voice | `gw/voice/event`, `state`, `rpc/*/res/voice` | `gw/voice/cmd`, `voice/turn`, `health/voice`, `rpc/*/req` | `health/voice` (retained) | ok |
| camera | `cmd` | `event`, `camera/*`, `health/camera` | `health/camera` | ok |
| sysmon | none | `health/system` | `health/system` | ok |
| recorder | `rec/cmd` | `rec/event` | none | ok |
| button | none | `gw/button/cmd` | none | ok |
| console | `state`, `gw/status`, `gw/remote/event`, `camera/+` | `gw/remote/cmd` | none | ok |
| brain | `state`, both events, `camera/+`, `voice/turn`, `health/+`, `gw/status`, `rec/event`, `rpc/*/req` | `gw/remote/cmd`, `gw/planner/cmd`, `rpc/*/res/*`, `rec/cmd` | none | ok |

No `cid` remains. `GatewayStatus` fields match `deploy.sh` and the dashboard. `HealthReport` metric and `info` keys match
between `sysmon` and `observe.assess`. `VoiceTurn` fields match `observe`. **`test_acl_contract.py` hard-codes the client list
instead of reading each client's `subscriptions()`; only the gateway is live.** The match above is by my reading, so a real
broker is still needed (NET5).

#### 3.4 systemd sandboxing and permissions [V, by reading]

| Service | Writes | Allowed by | Result |
|---|---|---|---|
| body | `/var/lib/spider/estop.latch`, `/tmp/*.ipc` client | `StateDirectory=spider`, `ReadWritePaths=/tmp` | ok |
| lidar | `/tmp/*.ipc` bind | `ReadWritePaths=/tmp` | ok |
| recorder | `/var/lib/spider/rec`, `/tmp/*.ipc` | `StateDirectory=spider`, `ReadWritePaths=/tmp` | ok |
| voice | HF cache only | `ReadWritePaths=/opt/spider/models/hf` | ok |
| gateway, camera, sysmon, button | none | read-only is enough | ok |

`/etc/spider/secrets` is 750 spider with 400 files, and every service runs as `spider`, which reads them. `mosquitto` reads
`/etc/mosquitto/spider` by group. `mosquitto.service` and `ollama.service` keep the packaged essentials (`Type=notify`,
`ExecStartPre` run directories, `User=ollama`) and drop the network wait. Real units have not run on a Pi.

## Unresolved items

| Item | Status |
|---|---|
| Real Mosquitto: J2-01, conf parsing, ACL and will behaviour | **Not verified.** Not available here: conda-forge has no package, and I did not build from a downloaded archive. Replaced by NET5 |
| Everything on real hardware: timing, IRQ movability, FIFO, thermals, boot, power, servo limp, `#nP0` | Not run, by rule. RT1, HW1-HW5, B-F1, B6 |
| Whisper int8 Arabic latency; LFM2.5 speed and Arabic quality | Not run. V1, S1 |
| Ollama loading the LFM2.5-VL projector; `llama-server` flags at v0.9.0 (`-DLLAMA_CURL`, `-hf`) | Not verified. V6, M6 |
| CSI camera module against the `opencv` backend | Unknown which camera is fitted. A CSI module needs `picamera2`, which the venv does not provide |
| Pi OS home directory mode (J2-02) | Debian's adduser default confirmed **[S]**; Pi OS not confirmed |
| Executor steps S00-S23 beyond file blocks | I verified the file blocks and the final tree; I did not rerun the lead's rehearsal of every command |
| Tailscale ACL, AWS worker, Point-LIO | No accounts. M6, M7 |

Also unresolved: J2-09 above. `تقدم` is one edit from `قدم`, so V2 should watch false motion from it.
