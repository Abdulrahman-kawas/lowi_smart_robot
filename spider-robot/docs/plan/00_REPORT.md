# Spider robot: report for the owner

Date: 2026-11-10. This is a plan with tested code. **Nothing has run on the Pi, the server or the
robot, and the robot is not built yet.**

## What is being built

A six-legged robot you talk to in Arabic. It walks, stops itself near obstacles and answers out loud,
all with no network. When the network is there, your home server adds vision and harder questions,
and you can control and supervise it from Telegram and a dashboard. AWS starts only for a mapping job
you ask for, and then stops itself.

The plan takes the repo from 105 tests to 489 passing, in 135 changed or new files, across a new voice
package, a hardened body and gateway, and a brain that runs on your server.

## Key decisions

| Decision | Why |
|---|---|
| Every Move expires by itself: voice at most 2 s, remote at most 1 s | A spoken Stop is estimated to take 3.3-8.3 s on this hardware |
| A physical E-stop that cuts servo power, before any untethered walking | Every "E-stop" in software leaves the servos under torque |
| E-stop survives a crash and reboot; a hold-to-release button works with no network | A crash used to clear it silently |
| The gateway enforces caps, a 2 s Stop hold-off and a single-use photo confirmation for remote release | A bad brain cannot bypass them |
| Common commands use a fixed grammar before any model; the model may only choose a motion your words named | Fast, and a hallucination cannot start a walk |
| Vision and cloud answers can only be spoken | A sign in front of the camera cannot give orders |
| Local control uses passwords on loopback; only the server uses certificates | A wrong clock or expired certificate cannot stop local control |
| Whisper `tiny` stays on the Pi by default; a one-line switch to the server waits for a measurement | Your decision 3 stands until the bench says otherwise |

## Judge's verdict

Two independent plans tied at 80 of 110: one stronger on body and safety, the other on interfaces and
voice speed. They were merged part by part, and every one of the judge's 25 required changes was closed.
The merged plan scored **84 of 110**, with 8 new blocking problems, all in the path from the Mac to the
real robot and in a Whisper timeout. I fixed all 8. **The process allows two review rounds, so the
judge has not checked those last fixes.** Full detail: `05_JUDGE_VERDICT.md`.

## Top risks, in the order you would hit them

1. **Everything on real hardware is unproven.** Expect the Pi and server steps to need correction.
2. **The LiDAR may have its IMU off from the factory.** Unitree's documents disagree, and without an
   IMU the robot refuses to walk. Step P05 checks it.
3. **The Python control loop on Core 0 is unproven.** RT1 decides, and if it fails later work changes.
4. **The LiDAR cannot see low objects or stair edges when mounted upright**, and it misses narrow ones
   like chair legs some of the time. There is no cliff sensor. Keep it away from stairs. An inverted
   mount is recommended.
5. **A spoken Stop is slow, and Arabic recognition is weak:** Whisper `tiny` has 63.4% and 90.9% word
   error on Arabic test sets. The small command vocabulary is what makes this workable.
6. **Your server's memory is tight** with both models, at about 5.7 GB free.
7. **No battery monitor or servo current sensing.** A fuse and a hardware alarm are the only protection.

## Monthly cost

| Use | About |
|---|---|
| Home only | $8.50, nearly all electricity |
| Typical | $11 |
| Heavy AWS, 60 h of mapping | $49 |

Prices read 2026-11-09 and 2026-11-10; some are third-party. Volumes are assumptions. Hardware to add
for the E-stop is about $25-45.

## What to do first

Give `04_EXECUTION_PLAN.md` to your executor agent and start at **S00**, which commits your uncommitted
work so everything can be rolled back. Steps S00-S23 run on the Mac and change only the code. The first
step that needs you is **P01**, preparing the Pi.

Before any walking, buy the E-stop parts: a mushroom switch, relay, fuse and release button. Size the
relay from your own current measurement in P09.

## The files

| File | What it is |
|---|---|
| `01_SYSTEM_DESIGN.md` | Requirements, architecture, contracts, safety, security, ADRs |
| `02_FILE_MAP.md` | Every file changed and where it runs |
| `03_ROADMAP.md` | Milestones and pass/fail gates |
| `04_EXECUTION_PLAN.md` | The one file for the executor |
| `05_JUDGE_VERDICT.md` | Scores, merge decisions, rejected ideas, unresolved items |
| `06_VALIDATION.md` | What was run, real results, and what was not |
