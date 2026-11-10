# Spider robot: validation

What was actually run for this plan, on 2026-11-10, and what was not. Machine: Mac, Apple Silicon,
uv 0.12.17. Nothing here touched a Pi, a real broker, the home server, the robot or a cloud account.

## 1. Final code on a fresh copy

Fresh copy of the working tree (excluding `.venv` and `docs/plan`), one baseline commit, then:

```
git apply --check _work/lead/merged.patch && git apply _work/lead/merged.patch
135 files changed, 11879 insertions(+), 268 deletions(-)
```

| Package | Baseline | `pytest` on Python 3.13 | `pytest` on Python 3.12 (Pi and CI) | `ruff check .` | `uv lock --check` |
|---|---|---|---|---|---|
| common | 9 | 25 passed | 25 passed | All checks passed! | Resolved 15 packages |
| body | 47 | 100 passed | 100 passed | All checks passed! | Resolved 26 packages |
| gateway | 16 | 169 passed | 169 passed | All checks passed! | Resolved 27 packages |
| voice | absent | 120 passed | 120 passed | All checks passed! | Resolved 54 packages |
| brain | 33 | 75 passed, 2 warnings | 75 passed, 2 warnings | All checks passed! | Resolved 108 packages |
| **Total** | **105** | **489** | **489** | | |

Commands, per package: `uv run -q --all-extras --frozen pytest -q`, `uv run -q --all-extras --frozen
ruff check .`, `uv lock --check`. The two warnings are a third-party `SyntaxWarning` in
`google/genai/types.py`, present at baseline.

**These tests use simulators and fakes.** The real Whisper, Piper, Ollama, `llama-server`, Mosquitto
and all hardware stop at the fake boundary.

## 2. The execution plan, rehearsed

`04_EXECUTION_PLAN.md`, 39 steps. Steps S00-S23 run on the Mac.

| Check | Result |
|---|---|
| A scripted rehearsal ran every S step's commands on a clean copy | ALL OK, final version |
| Tree after S00-S23 against the merged patch | 135 files compared, 0 different |
| Index line ranges against step markers (independent check) | 39 rows, 0 wrong |
| `apply_step.py` | Verifies each file by SHA-256 and each search block occurs exactly once |

### Dry run with a low-capability agent

`model: sonnet`, `effort: low`, given only the plan and a clean copy. Reports:
`_work/dryrun/REPORT.md`, `REPORT_2.md`.

| Run | Steps passed | Findings |
|---|---|---|
| 1 | 24 of 24 | 13 guesses: output noise on first `uv run`, no Mac prerequisites, no resume point for P and Q, gaps in P and Q |
| 2, after fixes | 23 of 24; S09 failed once | 10 items, N1-N10 |

**S09 failure (N1):** `1 failed, 99 passed`. The failing test was not captured. The strongest candidate
is `test_snapshot_publishes_jpeg`, which I also saw time out once on a first run after a new virtual
environment: its first use imports OpenCV, under a 5 s limit. I raised that limit to 60 s and two other
wait limits to 30 s. The cause is inferred, not proven. After the change: three runs on a deleted
`.venv` with 14 busy processes all printed `100 passed`.

**The agent's loop kept going past the S09 mismatch**, against rule 3, and it says so. It extracted
commands mechanically rather than following each step by hand, which is a less strict test of a real
low-cost agent than it sounds.

**After run 2** I fixed N1-N5 and N7 and re-ran the rehearsal. The dry-run agent was not run a third
time. N6 needs no change: the `sed` range matches `robot.example.yaml`. N8-N10 stand as accepted: they
are owner-facing items in HUMAN STEP blocks.

## 3. Mutation checks

| Who | Scope | Result |
|---|---|---|
| Judge, round 2 | 38 mutations on the merged code before the last fixes | 36 caught. The 2 uncaught were J2-12 |
| Lead | Removing the startup relax (R-13) | Caught |
| Lead | The two J2-12 mutations, after adding tests | Both caught |

The judge's round 1 attack scripts all passed against the merged code in round 2.

## 4. NOT VALIDATED

Every step whose ID starts with `P` or `Q` is **NOT VALIDATED**:

| Step | Needs |
|---|---|
| P01-P10 | The Pi, servos, LiDAR and the robot |
| Q01-Q04 | The home server, Telegram, Tailscale and AWS |
| Q05 | Two weeks of operation and the owner's approval |

## 5. Everything still unverified

| Item | Why | Replaced by |
|---|---|---|
| **The judge has not reviewed the fixes for J2-01 to J2-08** | The process allows two rounds | Listed in `05_JUDGE_VERDICT.md` |
| Mosquitto loading the config and ACL; refusing a listener with a missing certificate | No broker here | P02, P03, P07 |
| Any Pi timing, IRQ movability, FIFO, thermals, boot time with no network | No hardware | RT1, HW5, B-F1 |
| Python 50 Hz loop on Core 0 under load | Figures scale Mac measurements by an assumed 6-10× | RT1 |
| Whisper tiny int8 Arabic latency and accuracy | Nearby published figures only | V1, B-V1, V2 |
| LFM2.5-350M speed, JSON validity, Arabic quality, `maxLength` enforcement | Not run | S1 |
| Router token budget | Measured with the real tokenizer by both planners; not re-run by the judge or the lead | S1 |
| Piper and `espeak-ng` on the Pi; aarch64 wheels at install time | Not run | P02, V3 |
| Ollama loading the LFM2.5-VL projector | Liquid's pages conflict; the planner's download was denied by the permission system and not worked around | V6 |
| `llama-server` v0.9.0 build flags and `-hf` | Not built | Q01 |
| L2 factory defaults, work-mode bits, two-sided scan geometry, warm-up time | The manual and SDK disagree | HW1 |
| `lidar_bridge.cpp` against the real SDK | Syntax-checked against stubs by the planners; CI builds it | CI, P02 |
| `#nP0` on the SSC-32U and RDS3218 limp behaviour | Undocumented | HW2 |
| Servo stall current, brown-out, relay rating, cliff and low-obstacle behaviour | No hardware | HW1, HW4, B6 |
| Speech-onset false-stop rate near servos | No hardware | V4 |
| Tailscale relay behaviour on this link | Published figures are anecdotal | NET2 |
| Telegram and dashboard end to end | No accounts | Q02, Q03 |
| Point-LIO on hexapod motion, AWS scripts, NIM trial limits | No accounts or recording | Q03, Q04 |
| CI workflow | Never executed on GitHub | First push |
| Shell scripts | `bash -n` only | P02, Q01, Q04 |
| Pi OS home directory mode; a CSI camera | Unknown here | P02, P01 |

## 6. Reproducing this

`_work/lead/merged.patch` is the whole code change. `_work/lead/tools/` holds the scripts that generate
`04_EXECUTION_PLAN.md` and `02_FILE_MAP.md` from it, and run the rehearsal. The real repository's git
state is unchanged by this work: only `spider-robot/docs/plan/` was added.
