# 13. Roadmap

Each milestone can be tested on its own and leaves the robot working. A failed gate stops progress.
Time estimates are for one developer **[E]**.

## M0: Baseline and CI (half a day, Mac)

Commit the uncommitted work. Apply the protocol and CI files.
**Gate:** CI green; all packages pass `pytest` and `ruff`; `uv lock --check` passes.

## M1: Software safety core (2 days, Mac)

Protocol v3. Body fixes D1-D6, D10, D11, D15, D16, D18, camera service. Gateway with caps, lateness and
release rule.
**Gate:** all regression tests pass. Simulator run through a real Mosquitto on the Mac, if installed.

## M2: Pi bring-up, no motion (2-3 days, Pi, servos unpowered)

OS, tuning, firewall, broker, certificates, bridge, services.
**Gate, all required:**
- HW1: L2 data, IMU, sector map correct against known objects; low-object finding confirmed.
- RT1: control timing under load, 1 h. **This is the most important gate in the plan.**
- NET5: every forbidden publish refused.
- FI1-FI5 (servos unpowered).

## M3: First motion on a stand (2 days, human present)

**HUMAN STEP** throughout. Robot on a stand, feet in the air, cut-off within reach. Calibrate. HW2 part
one (what `P0` does).
**Gate:** RT2; FI1, FI2 and FI9 with servos powered; no jump on any startup or release.

## M4: Physical E-stop and floor walking (2-3 days, human present)

Fit the switch, relay, fuse, watchdog timer and low-voltage alarm. Move the LiDAR mount per HW1.
**Gate:** HW2, HW3, HW4, HW5; RT3 reflex test, 20 runs. **No untethered walking before this passes.**

## M5: Voice on the Pi (3-4 days)

Install models. Bench first, integrate after.
**Gate:** V1, V2, V3, V4, V5, S1; FI6, FI7. If V2 or V1 fails, take the fallback ladder in
`PLAN_14_open_questions.md` before going further. N-04: everything works with no network.

## M6: Server, remote control, vision, cloud (3-4 days)

Server setup; brain moves from EC2; Tailscale; remote caps; release flow; vision; Kimi via NIM with
`moonshotai/kimi-k3`.
**Gate:** NET1-NET4; FI8, FI10; V6; a remote E-stop release works end to end and is refused with an old
frame; S2 24 h soak.

## M7: Recording, SLAM, on-demand AWS (3-5 days)

**Gate:** a recording survives a power cut mid-job; Point-LIO produces a usable map from a real
recording; the worker stops itself with the link home cut; the budget alarm is in place.

## M8: Hardening and cleanup (ongoing)

Delete the EC2 and AWS IoT files once M6 has run for two weeks. Optional keyword spotter if V4 calls for
one. Optional cliff detection with an inverted LiDAR. Optional GPU server.
**Gate:** one week of normal use with no unexplained restart.

## What is kept, changed, deleted

**Kept:** the wire protocol's shape; IK and gait (`kinematics.py`, `gait.py`); `SafetyGuard` and the
corridor logic; `MqttLink`; the planner, graph, tools, policy, memory, skills, Telegram and dashboard;
`spider-calibrate`; the PCA9685 driver as an alternative.

**Changed:** see `FILE_MAP.md`. Principal: `protocol.py` (v3), `robot.py`, `main.py`, `hw/lidar.py`,
`hw/servos.py`, `hw/camera.py`, `lidar_bridge.cpp`, `gateway.py`, `robot_client.py`, `telegram.py`,
`server.py`, all unit files, `setup_pi.sh`, the ACL, and the certificate script.

**Deleted at M8, once the home server has proved itself** (agreed: keep them until then, so these are
not in `code.patch`): `infra/ec2/` (all five files), `infra/aws/iot_setup.sh`,
`infra/aws/body-policy.json`, `infra/aws/brain-policy.json`. The commands are in `FILE_MAP.md`.

## Order rationale

The order follows the agreed build order, with hardware gates put where they catch problems earliest.
RT1 comes before any motion, because if Python cannot hold the loop, everything after it changes. The
physical E-stop comes before floor walking, and before voice, so that voice testing happens on a robot
that can be stopped by hand.
