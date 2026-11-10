# Validation

Machine: Mac, Apple M2, macOS, uv 0.12.17, package venvs on Python 3.13.9. Run 2026-11-09 and 2026-11-10. Output below is copied from the runs. Paths shortened to `$SCR`, the scratch folder.

**Nothing has run on the Pi, the server, the robot, a real Mosquitto broker, or any cloud account.**

## 1. Final result: patch on a fresh copy

```bash
rsync -a --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude .ruff_cache \
  --exclude spider-robot/docs/plan <repo>/ $SCR/fresh/
cd $SCR/fresh
git apply --check $DEL/code.patch && git apply $DEL/code.patch && echo APPLIED_OK
for p in common body gateway voice brain; do
  (cd spider-robot/$p && uv run --all-extras pytest -q | tail -2; uv run --all-extras ruff check . | tail -1)
done
```

```
APPLIED_OK
=== common
24 passed in 0.32s
All checks passed!
=== body
60 passed in 5.10s
All checks passed!
=== gateway
101 passed in 4.72s
All checks passed!
=== voice
81 passed in 0.89s
All checks passed!
=== brain
70 passed, 2 warnings in 48.28s
All checks passed!
```

Total 336 tests. The baseline was 105 (9, 47, 16, 33). The two brain warnings are also present before this patch.

Patch: 107 files, 7709 insertions, 164 deletions. SHA-256 `c50e48957b0a9b4f16693c77d1e0bd64544700cfdab177316d03c4cdf713b82a`.

`uv lock --check` passed in all five packages. Installed entry points seen: `gateway/.venv/bin/spider-health`, `voice/.venv/bin/spider-voice`, `voice/.venv/bin/spider-voice-bench`.

A search for `TODO`, `FIXME`, `pseudocode` and `rest unchanged` in code, shell, YAML and unit files found nothing.

## 2. Defects reproduced on the unmodified baseline

Script: `$SCR/scripts/baseline_defects.py`, against the baseline gateway and servo bank.

```
D1 sequence seen by body after voice Stop: ['move', 'stop', 'move']
D1 events delivered to planner: []
D3 jitter sigma=0.0 ms: sends=2500 mean_gap=40.0 ms, gaps>45ms=0.0%
D3 jitter sigma=0.2 ms: sends=2012 mean_gap=49.7 ms, gaps>45ms=48.5%
D3 jitter sigma=0.5 ms: sends=1965 mean_gap=50.9 ms, gaps>45ms=54.5%
D3 jitter sigma=1.0 ms: sends=1950 mean_gap=51.3 ms, gaps>45ms=56.4%
D3 jitter sigma=2.0 ms: sends=1948 mean_gap=51.4 ms, gaps>45ms=56.9%
```

"D1" here is the plan's D1. "D3" in this output is the servo slip, listed as **D2** in `PLAN_00_index.md`. In the first run the same script printed a line about liveness from garbage input; it showed nothing conclusive, so that defect is claimed from reading `gateway.py:89` and is covered by `test_invalid_payloads_do_not_count_as_life`.

The fixes are proved by `test_voice_stop_is_not_undone_by_the_next_planner_renewal`, `test_voice_stop_ends_a_planner_walk_for_good` (real gateway and simulated body) and `test_ssc_keeps_25_hz_under_tick_jitter`.

## 3. Existing tests changed

Only these three existing tests were edited, all in `gateway/tests/test_gateway.py`:

| Test | Change | Why |
|---|---|---|
| `test_stop_with_future_clock_does_not_block_other_sources` | Waits out the 2 s hold-off | The hold-off now applies whatever the clock says |
| `test_only_owner_side_sources_can_release_estop` | Renamed `test_release_without_a_confirmed_frame_is_refused_for_every_source` | Decision 8: a release needs a frame |
| `test_simulated_body_stops_when_remote_source_disappears` | Voice stands the robot; waits for voice's pose hold to end | Remote can no longer wake a limp robot |

## 4. Measurements on the M2

`$SCR/scripts/m2_bench.py`, body venv:

```
tick us (walking): {'p50': 42.2, 'p99': 198.8, 'max': 277.6, 'mean': 59.7}
LidarProcessor.process n=2666 us: {'p50': 106.5, 'p99': 149.0, 'max': 1025.5, 'mean': 111.7}
LidarProcessor.process n=5333 us: {'p50': 111.6, 'p99': 149.0, 'max': 172.6, 'mean': 114.2}
feed.handle(imu) us: {'p50': 0.8, 'p99': 0.9, 'max': 19.3, 'mean': 0.9}
state json us: {'p50': 6.3, 'p99': 7.0, 'max': 30.1, 'mean': 6.3}
parse_command us: {'p50': 1.2, 'p99': 1.3, 'max': 1240.7, 'mean': 1.5}
```

`$SCR/scripts/zmq_cost.py`, separate publisher process, subscriber CPU only:

```
zmq.asyncio sub, 500 Hz: 2500 msgs, 7.0s, subscriber CPU 0.639s = 256 us/msg = 9.1% core on M2
zmq.asyncio sub, 100 Hz: 500 msgs, 7.0s, subscriber CPU 0.172s = 343 us/msg = 2.5% core on M2
```

## 5. Other checks

**Arabic token budget**, real LFM2.5-350M `tokenizer.json`, `python -I`, downloaded to its own folder:

```
max json tokens: 37
mean chars/token (say only): 1.76
worst-case per-char bound: chars->tokens ratio: 0.78
prefix tokens before say text: 7
```

Second set, sentences near the 60-character limit, and the shipped system prompt:

```
system tokens: 64
chars=52 say_tokens=36 json_tokens=45
worst tokens/char: 0.692
```

The longest allowed reply is therefore at most 60 x 0.78 + 9, or about 56 tokens, under `num_predict: 80`. Only the tokenizer was used; the model has not been run.

**Bag conversion**, `rosbags` 0.11.9, on a synthetic SPLR file including a truncated last record, read back with the same library:

```
{'clouds': 1, 'imu': 1}
cloud 100500000000 2 24 ['x', 'y', 'z', 'intensity', 'ring', 'time'] [1.0, 4.0] [5, 7] [0.01, 0.02]
imu 100700000000 9.8 1.0
```

**MQTT link against a real broker process** (amqtt, a Python broker, **not Mosquitto**), with username, QoS 1:

```
publish ok: True
received: t/x b'hello'
```

**C++ bridge:** `clang++ -std=c++17 -fsyntax-only -Wall -Wextra` printed no warnings. This was **against stub headers I wrote** for `zmq.h` and `unitree_lidar_sdk.h`, modelled on the published SDK header. It proves the syntax and types against those stubs only. It has not been compiled against the real SDK or linked.

**Shell:** `bash -n` passed on every script in `infra/`. JSON policy file parses.

**URLs that returned 200 or 206:** `ar_JO-kareem-low.onnx` and `.onnx.json` at `piper-voices` v1.0.0; `LFM2.5-VL-1.6B-Q4_0.gguf`; `LFM2.5-350M-Q4_K_M.gguf`.

**PyPI on 2026-11-09:** aarch64 wheels listed for `ctranslate2` 4.8.5, `piper-tts` 1.8.0, `webrtcvad-wheels` 2.0.14.post1, `onnxruntime` 1.31.1. PyAudio has source only.

## 6. Not verified

| Item | Why | First checked at |
|---|---|---|
| Everything on the Pi: timing, heat, power, audio | No hardware access, by rule | M1, M2 |
| Pi estimates derived from the M2 | 6-10x factor is assumed | B1 |
| Real Mosquitto loading `mosquitto.conf` and the ACL | Mosquitto is not installed here. The ACL file is checked by a test that parses it and matches topics; broker behaviour is not | M1 |
| `use_identity_as_username` with a global `password_file` on 2.0.21 | From the man page wording only | M1 |
| nftables, systemd units, `irqaffinity` | Linux and root required | M1 |
| `setup_pi.sh`, `setup_server.sh`, `deploy.sh`, `mqtt_passwords.sh` | Syntax-checked only | M1, M3 |
| Real adapters: faster-whisper, Piper, PyAudio, aplay, Ollama streaming, espeak-ng | Tests use fakes and a mock HTTP transport. The real Piper and Whisper APIs are written from their docs | M2 |
| Ollama running LFM2.5-350M and honouring `maxLength` | Not installed | M2 |
| `#nP0` stopping pulses on the SSC-32U | Not in the guide | M1, B6 |
| `llama-server` with LFM2.5-VL, and CPU speed | Not run | M3 |
| Real Telegram, dashboard page in a browser, Tailscale | No accounts. Telegram is tested with a mock transport; the page's JavaScript was not executed | M4 |
| NIM endpoints | No account. Availability comes from NVIDIA's pages only | M5 |
| Point-LIO, Dockerfile, `run_slam.sh`, `process_job.sh` | Docker and a real recording needed | M6 |
| AWS worker scripts and IAM policy | No account | M6 |
| CI workflow | Not pushed | M0 |
| Arabic quality of every model | Needs the owner's voice | M2 |
| Evidence for `tiny` on a Pi 4 | Secondary reports with differing setups; the 3-8 s range is an estimate | B-V1 |
