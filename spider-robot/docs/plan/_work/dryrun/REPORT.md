# Dry run report: 04_EXECUTION_PLAN.md, steps S00-S23

Method: I read the opening rules and index, then each step's non-file text. I extracted each step's
```bash block mechanically (so no retyping) and ran it from the repo root of the copy. Every step
committed cleanly; PROGRESS.md last line is `S23 done`; `git status --short` was 0 lines before and after each step.

## Results

| Step | Result | Final check output |
|---|---|---|
| S00 | pass | `0` |
| S01 | pass | hash `b80ff7e5...003bc` (matches) |
| S02 | pass | `S02: 2 files written and verified`, `True` |
| S03 | pass | `25 passed in 0.31s` / `All checks passed!` |
| S04 | pass | `All checks passed!` / `compiled` |
| S05 | pass | `All checks passed!` / `compiled` |
| S06 | pass | `All checks passed!` / `compiled` |
| S07 | pass | `All checks passed!` / `compiled` |
| S08 | pass | five `...service:0` lines as expected |
| S09 | pass | `100 passed in 5.04s` / `All checks passed!` |
| S10 | pass | `All checks passed!` / `compiled` |
| S11 | pass | `All checks passed!` / `compiled` |
| S12 | pass | two `...service:0` lines as expected |
| S13 | pass | `169 passed in 12.81s` / `All checks passed!` |
| S14 | pass | `All checks passed!` / `compiled` |
| S15 | pass | `All checks passed!` / `compiled` |
| S16 | pass | `All checks passed!` / `compiled` |
| S17 | pass | `120 passed in 1.63s` / `All checks passed!` |
| S18 | pass | `All checks passed!` / `compiled` |
| S19 | pass | `All checks passed!` / `compiled` |
| S20 | pass | `75 passed, 2 warnings in 51.01s` / `All checks passed!` |
| S21 | pass | `shell-ok` |
| S22 | pass | `shell-and-json-ok` |
| S23 | pass | 25/100/169/120/75 passed, all lint clean, five `Resolved N packages` lines (15, 26, 27, 54, 108) matching |

24 of 24 steps passed. No failure. Every apply_step OK count matched the stated file count.

## Defects and guesses (S steps)

1. S04, S10, S14, S18 (first `uv run` in each new package). Expected output lists only
   `All checks passed!` / `compiled`. Real output also had stderr noise before them:
   `Using CPython 3.13.9 interpreter at: /opt/anaconda3/bin/python`, `Creating virtual environment at: .venv`,
   `Building spider-body @ file:///...`, `Built ...`, `Installed 21 packages in 35ms`.
   Plan text: "Then: ```All checks passed! compiled```" with the rule "any output differs ... Stop".
   Unclear whether this is a stop. The first command pipes only stdout through `tail -1`; uv's stderr is not filtered
   (S03 used `2>&1 | tail -1`, the others do not). I had to guess it is acceptable.
2. Whole plan: no prerequisite list for the Mac (uv installed, Python version, network or warm uv cache, rsync, git identity).
   uv picked an anaconda 3.13.9 interpreter; the plan never says which Python is required. Worked only because the
   cache or network was available; `--frozen` still downloads packages on a cold cache.
3. S00. `git add -A` also swept in `CLAUDE.md`, `graphify-out/cache/last_query_stamp`, and the plan itself. "Files touched:
   every currently uncommitted file" covers it, but the plan does not say whether stray files like these should be committed.
4. Rule 1 vs rule 7 vs rule 8. PROGRESS.md gets `Sxx done` lines, but P and Q steps (except Q05) never append a line
   and are HUMAN STEPs. "Its last line is the last finished step" is unusable after S23: resume point in P/Q is undefined.
5. S23 expected output has `75 passed in 46.65s` while S20 expects `75 passed, 2 warnings in 50.75s`. Rule 4 says
   "count of warnings" may differ only in S-step Stop text; S23 expected omits warnings while real output also omitted them
   (tail -1 only showed `75 passed in 46.43s`). Not a failure but an inconsistency between S20 and S23.
6. Rule 11 and Rule 12 vs P06: P06 says "This script starts `spider-body`, so it is yours to run", but the block is headed
   HUMAN STEP and rule 12 says starting spider-body is always a human step. "Yours" is ambiguous (owner's?).

## P and Q steps, read once, not run

- Global: HUMAN STEP blocks do not say how the executor gets "results" back or the exact BENCH_RESULTS.md format.
  Commit messages are given (P05-P10, Q03, Q04) but no `git add`/`git commit` commands, no check that
  `spider-robot/docs/plan/BENCH_RESULTS.md` exists, and no PROGRESS line. An executor must invent those.
- Many placeholders in prose only (`PI_USER`, `PI_HOST`, `PI_TAILSCALE_NAME`, `PI_TAILSCALE_IP`, `SERVER_USER`,
  `SERVER_HOST`, `REPLACE_WITH_THE_BY_ID_PATH`, `<value>`, `<id>`, `<job id>`). Rule 10 says never invent one, but there is
  no place to record them between steps (P03 and Q01 reuse PI_HOST/PI_USER from P01 by memory; a resumed session loses them).
- P01: step 6 "stop and decide before P02" for a CSI camera has no decision rule or owner contact path. References
  `01_SYSTEM_DESIGN.md` section 7, but the executor was told to read only this plan.
- P02: `rsync --exclude docs` excludes every directory named `docs` at any depth, not only `spider-robot/docs`. Expected
  output "next four print enabled" but the command prints for `spider-gateway mosquitto ollama spider-tune` only if all
  exist; `systemctl is-enabled` prints `enabled` on one line each; fine, but if the first fails the `;` chain continues silently.
  `ssh -t ... sudo reboot` then later steps do not say to wait for the Pi to return.
- P03: run from `spider-robot/infra/local` ("Directory"), but P03 commands use `mosquitto-tls.conf` under `~/spider-robot/infra/local`
  on the Pi (rsynced in P02 only if not excluded). `/etc/mosquitto/spider` is assumed to exist; created by setup_pi.sh? not stated.
  "number at least 1" while the grep -c result after a successful restart is exactly 1 or more; fine.
- P04: `sed` pattern has a trailing space after `ttyUSB0` and a fixed key `port:` with no way to tell which of several `port:`
  lines is the SSC. Expected output says "the `ssc` port line" but `grep -n 'port:' | head -3` may show LiDAR/MQTT ports instead.
  Stop-if says to replace the placeholder "before running the sed line", which contradicts the command order (ls first).
  The placeholder is not a value the executor knows; it must come from the ls output, with no rule on multiple devices.
- P05: `LIDAR_SET_WORK_MODE=<value>` undefined ("value 0 ... if the bit order above holds"): requires interpretation.
  Step 3 starts `spider-lidar`, but rule 12 and the plan never decide if that is allowed (it is not servo motion). Hardware-only.
- P06: `bench_jitter.sh` run from `~/spider-robot/infra/pi` but venv path is `/opt/spider/spider-robot/body/.venv`:
  two different install trees used with no explanation. Expected thresholds "on the shipped setting" never name which of
  the two printed JSON lines is "shipped" (it is the second run).
- P07: header says "After the executor has run the commands below" but the HUMAN block is placed before the Commands, and
  the Commands block has no host (they run on the Pi, "Directory: ~"; no ssh wrapper unlike P02). The heredoc script embeds
  `sudo cat` secrets and a fixed user list; expected output says `ALLOWED-DELIVERED` appears, no clear handling for a
  mosquitto_pub connect failure, and `acl-test-finished` always prints so cannot signal failure. References section 9.5 (FI1-FI5)
  outside the plan. `sudo systemctl stop spider-gateway` before test and start after: if the test fails the executor
  must still restart it; not stated.
- P08: all references (B6, RT2, HW2, B1, FI1, FI2, FI9) are in 01_SYSTEM_DESIGN.md; the rule says defined there, but the
  step's expected output is just "owner reports", with no numeric pass criteria in the plan.
- P09: no pass criteria for HW2-HW5, RT3, B-E1 in the step. "relay rated from your HW4 current measurement" needs a
  value that is not given.
- P10: Commands (enable camera/recorder, help) are placed after a HUMAN block whose step 5 enables voice; order of the
  executor commands relative to the human items is unstated. `sudo systemctl enable --now` there has no ssh wrapper.
  Thresholds ("target" stop recall, "V2 any false motion") are not defined in this file. `max_motion_age_s` set "from V1" has
  no formula.
- Q01: `sleep 30` vs the stated wait of "many minutes" and "30 minutes"; no retry loop. Expected output "an OK status" is not
  the literal text of llama-server `/health` (unspecified).
- Q02: HUMAN step mixes Mac, server and Pi actions (item 4 is on the Pi); `REPLACE_WITH_SPIDER_AT_PI_TAILSCALE_NAME`
  format is unexplained; "dashboard port from your brain.env" is ambiguous (default 8765?); `tailscale serve` machine unspecified.
- Q03: model id `kimi-k3` in text vs `kimi-k3.1-pro` elsewhere; "had no API on 2026-11-04" is a dated claim the executor cannot check.
  Stop condition "old or reused frame" has no way to detect it.
- Q04: `budget_alarm.sh` needs arguments (not stated); AWS account/credentials not covered by rule 10.
- Q05: only step in P/Q with executor commands that edits the repo; its precondition ("two weeks", "owner approved") is
  unverifiable by the executor, and it appends `Q05 done` although P01-Q04 never wrote a line.

Total defects/guesses recorded: 6 in S steps, plus the P/Q notes above (counted as 13 distinct ones in the final message: 6 + 7 grouped P/Q items).
