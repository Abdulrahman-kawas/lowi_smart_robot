# Dry run 2: 04_EXECUTION_PLAN.md (revised, 16,809 lines), steps S00-S23

Method as before: each step's bash block extracted mechanically and run from the copy's root; expected output compared by eye.
Final state: PROGRESS.md ends `S23 done`, working tree clean, one commit per step with the plan's messages.

## Results

| Step | Result | Final check output |
|---|---|---|
| S00 | pass | `uv 0.12.17 (635500036 2026-09-18 aarch64-apple-darwin)`, `git-identity-ok`, status listing, `0` |
| S01 | pass | hash `b80ff7e5...003bc` |
| S02 | pass | `S02: 2 files written and verified`, `True` |
| S03 | pass | `25 passed in 0.31s` / `All checks passed!` |
| S04-S08 | pass | `All checks passed!` / `compiled` (S08: five `...service:0` lines) |
| S09 | **FAIL (flaky)** | first run: `1 failed, 99 passed in 9.06s` then `All checks passed!`; expected `100 passed in 5.35s` |
| S10, S11 | pass | `All checks passed!` / `compiled` |
| S12 | pass | two `...service:0` lines |
| S13 | pass | `169 passed in 12.67s` / `All checks passed!` |
| S14-S16 | pass | `All checks passed!` / `compiled` |
| S17 | pass | `120 passed in 1.65s` / `All checks passed!` |
| S18, S19 | pass | `All checks passed!` / `compiled` |
| S20 | pass | `75 passed, 2 warnings in 52.58s` / `All checks passed!` |
| S21 | pass | `shell-ok` |
| S22 | pass | `shell-and-json-ok` |
| S23 | pass | 25/100/169/120/75 passed, lint clean, `Resolved 15/26/27/54/108 packages` |

23 pass, 1 fail (S09).

### S09 failure (first failure)
Output was `1 failed, 99 passed in 9.06s` (plan expects `100 passed`). The test name was not captured. Procedural
error on my side: my loop ran S07 to S23 in one background script and did not stop at the mismatch, so S09 was
committed and later steps ran. Rule 3 says stop. Afterwards, outside the plan, I ran the body suite three times:
`100 passed` every time (2.0-2.1s). So it looks like a timing-sensitive test failing while the machine was loaded
(that run was 9s vs 5s expected, and S07-S23 ran concurrently with my polling). Real plan defect: some body test is
flaky under load and the plan has no rule on re-running ("stop at once, do not fix"). Needs the failing test found
and made load-proof, or a rule that allows one re-run.

## Defects still present or new

N1. S09 flaky test (above). New or exposed this run.
N2. P01: SITE.env is written with four `VALUE_FROM_THE_OWNER` lines, but no command substitutes the owner's values
    (the HUMAN block says "puts them in ... in place of" without a command). The `ssh` line then runs with the literal
    placeholder. Also the HUMAN block comes before the Commands in the text, with no stated order between them.
N3. Q01 appends `SERVER_USER=VALUE_FROM_THE_OWNER` literally via printf; same substitution gap, and an executor must
    edit a command before running it.
N4. All "When finished" blocks contain `REPLACE_WITH_TODAY'S_DATE` and `PASTE THE OWNER'S RESULT TEXT HERE, UNCHANGED`
    inside a heredoc. Rule 10 says `REPLACE_...` is a secret placeholder never to invent a value for; here the executor is
    told to fill it. Conflict between rule 10 and the blocks.
N5. P05: step 4 says "Confirm the IMU reports", but Stop-if still says `roll_deg stays null`; no command or field name given
    for checking it. `<value>` is still chosen by the owner; fine, but `/opt/spider/bin/lidar_bridge` run line is in the HUMAN block.
N6. P04: the `sed` range `/^ssc:/,/^[a-z]/` assumes `ssc:` is a top-level key followed by an indented `port:`; unverifiable
    without the example yaml, and `grep -A1` assumes `port:` is the very next line.
N7. P06 Stop-if refers to "design's section 12", and P01/P07/P08/P09 refer to design sections; rule 7 now says those are for
    the owner, so acceptable. Pass limits in P06 for Core 0 and cyclictest are not in Expected output (only in step 5).
N8. Q03 step 6 still says `kimi-k3.1-pro had no API on 2026-11-04` (dated claim, executor cannot check; unchanged).
N9. Q04 step 1 `ACCOUNT_ID=<yours> EMAIL=<yours>`: placeholders with no SITE.env home; `<job id>` and `<id>` likewise.
N10. P07: the commands (ACL test) run before the HUMAN block that includes a reboot with Wi-Fi off; the stop-if on
     `ALLOWED-DELIVERED` is now present. `acl-test-finished` prints regardless. Minor.

## Status of each defect from report 1

1. uv stderr noise at first `uv run` (S04, S10, S14, S18): resolved. Not seen this run (S00 now checks uv; no noise in my output).
2. No Mac prerequisites: resolved ("Before you start, on the Mac", uv version pinned, S00 checks it).
3. S00 sweeping CLAUDE.md etc.: resolved (stated as on purpose).
4. PROGRESS lines for P/Q steps: resolved (every step has "When finished" with a PROGRESS line).
5. S20 vs S23 warnings inconsistency: resolved (rule 4 allows `2 warnings` to come and go).
6. P06 "yours to run": resolved ("the owner runs it and the executor does not").
P/Q items from report 1:
- Placeholders with nowhere to record (PI_USER etc.): mostly resolved by SITE.env; see N2, N3 for the remaining substitution gap.
- BENCH_RESULTS.md commit commands/format: resolved (cat >> blocks), but see N4.
- Pass criteria for HW2-HW5, RT3, B-E1, V2 etc.: resolved (numbers now in the blocks).
- P01 CSI decision rule: resolved (plan stops). Reference to design doc: resolved by rule 7.
- P02 `--exclude docs` too broad: resolved (`/spider-robot/docs`). Wait for reboot: resolved (`until ssh ... echo back`).
- P03 directory/path confusion: resolved; `/etc/mosquitto/spider` now a stated precondition.
- P04 sed pattern / which port line: resolved by the range and single-device check, with caveat N6.
- P05 `<value>`: partly resolved (owner decides it, guidance given); roll_deg wording is N5.
- P06 two install trees: resolved (directory now /opt/spider/spider-robot/infra/pi).
- P07 missing ssh host and command/human ordering: resolved (commands use ssh, human block says "after the executor's commands").
- P08-P10 pass criteria and P10 command ordering: resolved.
- Q01 `sleep 30` vs 30 minutes: resolved (60x30s loop). Health text now `{"status":"ok"}`.
- Q02 mixed machines / port / ssh target format: resolved (machine labels, 8765 default, example target).
- Q03 kimi model id: not resolved (N8).
- Q04 budget_alarm arguments: resolved (env vars given), placeholders remain (N9).
- Q05 unverifiable precondition: resolved (owner message required).

Remaining: 1 failure (S09 flaky) and 10 defects/guesses (N1-N10), of which N1 is the blocking one.
