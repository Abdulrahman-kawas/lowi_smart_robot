# Validation

Everything below was actually run, on 2026-11-09/10. Paths under my scratch folder are shortened to
`<scratch>`.

Environment: macOS, Apple M2, uv 0.12.17. **No test touched a Pi, a broker, a server, or a robot.**

## 1. The patch on a fresh copy

The working tree was copied afresh with the rsync command from the brief, given one baseline commit,
and `code.patch` was applied to it. Output of the final run, unedited:

```
$ git apply --check code.patch
exit 0
$ git apply code.patch
exit 0

=== common
$ uv lock --check
Resolved 14 packages in 3ms
$ uv run --all-extras pytest -q
15 passed in 0.32s
$ uv run --all-extras ruff check .
All checks passed!

=== body
$ uv lock --check
Resolved 26 packages in 3ms
$ uv run --all-extras pytest -q
88 passed in 5.23s
$ uv run --all-extras ruff check .
All checks passed!

=== gateway
$ uv lock --check
Resolved 26 packages in 4ms
$ uv run --all-extras pytest -q
37 passed in 2.03s
$ uv run --all-extras ruff check .
All checks passed!

=== voice
$ uv lock --check
Resolved 54 packages in 5ms
$ uv run --all-extras pytest -q
87 passed in 0.68s
$ uv run --all-extras ruff check .
All checks passed!

=== brain
$ uv lock --check
Resolved 107 packages in 4ms
$ uv run --all-extras pytest -q
58 passed, 2 warnings in 41.54s
$ uv run --all-extras ruff check .
All checks passed!

$ bash -n on every shell script
14 scripts, 0 with errors
$ python3 -m json.tool on the IAM policies
ok infra/aws/body-policy.json
ok infra/aws/brain-policy.json
ok infra/aws/worker/worker-control-policy.json
$ c++ -std=c++17 -Wall -Wextra -fsyntax-only (against stub headers I wrote)
exit 0
$ load example configs with the real validators
voice.example.yaml ok, hf.co/LiquidAI/LFM2.5-350M-GGUF:Q4_K_M
robot.example.yaml ok, broker 127.0.0.1 latch /var/lib/spider/estop.latch
$ make_local_certs.sh in a temp dir
exit 0
10 certificates
    DNS:spider-pi, DNS:localhost, IP Address:100.64.0.1, IP Address:127.0.0.1
```

Totals: **285 tests pass** (baseline 105: common 9, body 47, gateway 16, brain 33, and I re-ran those
in my copy and got the same numbers). Ruff is clean in all five packages.

## 2. Existing tests I had to change

Changing a test can hide a bug, so each one is listed with its reason.

| Test | Change | Why |
|---|---|---|
| `gateway/tests/test_gateway.py`, helper `beat()` and several calls | Timestamps now advance with the clock | The new lateness check treats a frozen timestamp as a message getting later and later, which is correct |
| `test_stop_with_future_clock_does_not_block_other_sources` | Clock advances past the 0.75 s stop fence | The fence is measured on the gateway's clock, so that a sender's clock cannot affect it |
| `test_lost_owner_stops_robot_and_voice_keeps_the_link` | Move duration below the remote cap | The test expected the owner to be lost before the Move ended; the cap now shortens the Move |
| `test_only_owner_side_sources_can_release_estop` | Replaced by two tests | The rule changed by agreed decision 8: voice is also refused, and remote needs proof |
| `brain/tests/test_robot_source.py` | Allows the planner topic as well | The brain now heartbeats as both sources |

No test was removed or weakened in `common` or `body`.

## 3. Defects reproduced on the unmodified baseline

`git archive` of the baseline commit, with a script calling the original code. Output, unedited, apart
from one log line about the deliberately wrong version:

```
D1 obstacle 1.0 m ahead, next cloud sweeps the far side: sector[0] 1.0 -> 8.0 (8.0 = reported free)
D2 body pitch during E-stop: 0.052 -> 0.262 rad; max servo change 34.3 deg
D3 E-stop during stand-up: internal height 0.055 -> 0.090 m; servo jump on release 32.8 deg within 60 ms
D4 SIGTERM under E-stop: estop=False mode=sitting target_height=0.035 (the robot is told to sit)
D5 new process after a latched E-stop: estop=False mode=relaxed
D6 wrong-version heartbeat refreshed the watchdog: True
D7 remote Move forwarded uncapped: vx=0.5 wz=2.0 duration=10.0
D8 heartbeat sent 1.9 s ago keeps the source alive; commands sent: ['move', 'heartbeat']
D9 remote E-stop release without frame or confirmation forwarded: estop_release
```

The D1 input is synthetic: two partial sweeps. That the real L2 delivers partial sweeps is derived
from the manual's rates and the SDK's `cloud_scan_num=18`, and HW1 confirms it on hardware.

## 4. CPU cost measured on the Mac

Inputs to the budget in `PLAN_04_budgets.md`. These are M2 numbers; the Pi numbers derived from them are
estimates.

Baseline code:

```
tick walking (FakeServoBank): p50=28.7us p99=195.7us max=9745.8us
state().model_dump_json(): p50=5.9us p99=13.5us max=41.6us
parse_command(Move): p50=1.1us p99=1.5us max=469.0us
emit(ack): p50=3.4us p99=7.8us max=176.9us
LidarFeed.handle(cloud 2667 pts): p50=177.4us p99=366.3us max=1607.0us
LidarFeed.handle(imu): p50=0.7us p99=0.9us max=19.5us
```

With the per-sector merge:

```
new LidarFeed.handle(2667 pts): p50=245.9us p99=657.2us
```

Voice matching:

```
StopWords.match: p50=14.2us p99=20.8us
grammar.match: p50=13.5us p99=59.2us
```

## 5. Arabic token budget

Measured with the real `tokenizer.json` from `LiquidAI/LFM2.5-350M` (Hugging Face), downloaded into its
own directory and read with `python -I`. Columns: tokens in the phrase, tokens in the JSON reply.

```
   3   15  chars=  4 words= 1  حاضر
   7   19  chars=  9 words= 2  لحظة أشوف
   8   20  chars= 15 words= 3  تمام، رايح قدام
  14   26  chars= 26 words= 5  حاضر، بمشي لقدام شوي وبوقف
  12   24  chars= 24 words= 5  ما فهمت عليك، ممكن تعيد؟
  16   28  chars= 35 words= 8  ما أقدر أتحرك الآن لأن في شيء قدامي
  25   37  chars= 55 words=10  شايف قدامي طاولة وكرسي على اليمين وباب مفتوح على اليسار
  30   42  chars= 59 words=11  أهلا وسهلا، أنا عنكبوت آلي بست أرجل، كيف أقدر أساعدك اليوم؟
  30   42  chars= 64 words=13  سأتوقف الآن وأنتظر أمرك التالي، قل لي إذا أردت أن أتحرك مرة أخرى
system prompt tokens: 39
```

So `num_predict: 64` covers the JSON wrapper plus a sentence of about 20 words. This measures the
tokenizer, not the model: **whether LFM2.5-350M actually keeps to 10 words in Arabic is untested**, and
S1 checks it.

## 6. Not verified

| Item | Why not | What verifies it |
|---|---|---|
| Anything on the real Pi: timing, thermals, IRQ steering, `mlockall`, FIFO | No hardware access, by rule | RT1, HW5 |
| Real Mosquitto: TLS, ACL syntax, retain, will | Mosquitto not installed here | NET5, M2 gate |
| Servos, SSC-32U, `P0` behaviour | No hardware | M3, HW2 |
| L2 behaviour: partial sweeps, FOV, IMU, work mode | No hardware | HW1 |
| `lidar_bridge.cpp` against the real SDK | Checked only against stubs I wrote from the published header | CI `bridge` job, M2 |
| **Ollama loading the LFM2.5-VL projector** | I tried to download Ollama to test it. **The permission system denied the download, and I did not look for a way round it** | V6 |
| **Real LFM2.5-350M output, including Arabic quality and JSON validity** | Same | S1 |
| Whisper, Piper, webrtcvad running on real audio | Adapters tested with fakes; the real packages install, but I did not run real models | V1, V2, V3 |
| All voice latency numbers | Estimates only, labelled | V1, V3, V4, S1 |
| `spider-update.sh`, `setup_pi.sh`, `setup_server.sh`, `spider-tune.sh`, `bench_jitter.sh`, nftables, systemd units | `bash -n` only; they need the target machines | M2, M6 |
| Point-LIO container, `run_slam.sh`, point field layout | Marked not verified in the Dockerfile | M7 |
| AWS scripts and policy | JSON and shell syntax only; no account used | M7 |
| The CI workflow | Not run | First push |
| `GpioKick` on real GPIO | Logic tested with fakes | HW3 |
| Prices | Mostly third-party trackers; vendor pages could not be opened | `PLAN_11_cost.md` lists each |
