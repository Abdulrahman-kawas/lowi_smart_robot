# Judge round 2: merged plan

Run on 2026-11-10 on a Mac (Apple Silicon, macOS, uv 0.12.17). Nothing touched a Pi, a server, the
robot, a broker of the owner's or a cloud account. Labels: **[V]** verified by me (code read at the
cited line, or run by me); **[S]** published source; **[E]** estimated. File references without a
prefix are in the merged tree.

**Verdict: the merged code is good and every round 1 BLOCKING defect in the code is closed. The plan
cannot be handed over yet: 8 new BLOCKING findings remain, all small, all in the execution path from
the Mac to the robot and in the voice timeout.**

## 1. Real test results

Fresh copy with the brief's rsync command, one baseline commit, `git apply --check` then `git apply`
of `merged.patch` (SHA-256 `41b69bcf...`). 132 files, 90 new, 42 changed, as the file map says **[V]**.

| Package | pytest | ruff | `uv lock --check` |
|---|---|---|---|
| common | 25 passed | All checks passed | ok |
| body | 100 passed | All checks passed | ok |
| gateway | 157 passed | All checks passed | ok |
| voice | 113 passed | All checks passed | ok |
| brain | 74 passed, 2 warnings | All checks passed | ok |
| **Total** | **469** | | |

The lead's counts are accurate **[V]**. `pytest` and `ruff` exit codes were captured and are 0 in all
five; raw output in `<judge scratch>/results_m2.txt`. The two brain warnings are the same third-party
`SyntaxWarning` as round 1.

**Execution plan file blocks [V].** I extracted `apply_step.py` from S01, ran it for S00-S23 on a fresh
baseline, and diffed against the merged tree: every step reported "written and verified", and the
resulting tree is byte-identical to `merged.patch` applied. `uv sync --frozen` with the plan's exact
extras and groups resolves for all four deployed packages (dry run).

### 1.1 Mutation check on the merged code [V]

38 mutations, each breaking one fix, running that package's tests, then restored. Script:
`<judge scratch>/scripts/mutate_m2.py`. **36 caught, 2 not.** R-13's two mutations are both caught
(`test_startup_relaxes_servos_before_the_first_tick`,
`test_startup_under_a_latched_estop_does_not_touch_the_servos`).

| Not caught | Meaning | Finding |
|---|---|---|
| `_too_old` removed from the early-act path (`pipeline.py:260`) | Stale LLM motion through streaming has no test | J2-12 |
| `_stt_running < workers` replacing `max(1, workers - 1)` (`pipeline.py:171`) | "A long utterance never takes the last worker" has no test | J2-12 |

### 1.2 Round 1 attacks re-run on the merged code [V]

`<judge scratch>/attack_m2.out`, adapted from `attack_a.py` and `attack_b.py`:

```
A1 planner Stop then voice Move (want stop,move): ['stop', 'move']
A2 voice Stop, planner Stop, planner Move 0.2 s later (want no move): ['stop', 'stop']
A3 planner Move 0.76 s after voice Stop (want no second move): ['move', 'stop'] planner got: ['preempted', 'rejected']
A4 reuse of challenge after a new E-stop (want exactly one release): ['snapshot', 'estop_release', 'estop'] E-stop release needs a confirmed fresh camera frame
B4 stale heartbeat (want move, stop): ['move', 'stop'] alive: False
Btn1 button while voice owns (want rejected): rejected voice is in control
Btn2 button when idle (want estop_release forwarded): estop_release
Btn3 button sending Move (want rejected, no move): the button may only release an E-stop estop_release
B1 staged wake: height when each new leg first commanded: [(0, 3.5, 1), (8, 3.5, 2), (16, 3.5, 3), (24, 3.5, 4), (32, 3.5, 5), (40, 3.5, 6)]
B2 E-stop: height change 0.0 servo change 0.0
B3 SIGTERM under E-stop (want True, estop): (True, 'estop')
```

All round 1 defects are gone. Two new results:

```
Skew brain +2 s, console on Pi, same source (want accepted): arrived 2000 ms late; network is congested
slower than timeout: ['TimeoutError', 'TimeoutError', 'TimeoutError'] | pool threads still running after timeouts: 1
```

## 2. Closure of R-01 to R-13

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

### Changes beyond the list

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

## 3. Attack on the merged result

### 3.1 What breaks first, in order

1. **P02 itself** fails on the broker restart (J2-01), and possibly earlier on the home-directory copy (J2-02).
2. **P05** collides with the running LiDAR service (J2-03).
3. **P06** starts the body against the executor's own rule (J2-04).
4. **M3 and M4 cannot be run:** nothing can send a stand or a Move before voice or the brain exist (J2-05).
5. **The SSH fallback console** cannot run as documented (J2-06).
6. **Voice dies quietly if Whisper is slower than its 8 s timeout,** which is inside the plan's own estimate once two utterances overlap (J2-07).

### 3.2 Findings

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

### 3.3 Contract check across packages [V, static]

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

### 3.4 systemd sandboxing and permissions [V, by reading]

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

## 4. Final scores for the merged plan

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

## 5. Remaining BLOCKING findings

Eight remain, each a small change: **J2-01, J2-02, J2-03, J2-04, J2-05, J2-06, J2-07, J2-08** (section 3.2). No BLOCKING defect
remains in the safety logic of the body, gateway or voice stop path. The plan is not ready to hand to the executor until all
eight are fixed. J2-02 is confirmed for Debian's default but not for Pi OS.

## 6. Unresolved items

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
