# Spider robot

A six-legged walking robot (18 servos: 6 legs x coxa/femur/tibia) with a Unitree L2 4D LiDAR,
a Raspberry Pi 4 body controller, and a cloud/local "brain" that plans with Claude (phase 1,
AWS) or Liquid AI LFM2.5 (phase 2, local) and sees with Liquid AI LFM2.5-VL.

```
common/   wire protocol + MQTT link (shared)
body/     runs on the Pi: servos, IK, gait, LiDAR safety reflexes, camera, cloud link
gateway/  runs on the Pi: the only sender of commands to the body
voice/    runs on the Pi: VAD, speech recognition, stop words, grammar, router, speech
brain/    runs on EC2 or a local PC: LangGraph planner, tools, vision, supervision dashboard
infra/    AWS IoT, EC2, Raspberry Pi and local-broker setup scripts
```

Safety model: the body never waits for the cloud to be safe. It stops by itself near obstacles
(LiDAR), when the brain goes quiet (heartbeat watchdog), when a command expires, and when it
tilts. The brain adds owner approval on top (dashboard, autonomy modes).

## Run the simulator (no hardware)

```bash
mosquitto -c infra/local/mosquitto-sim.conf &
(cd body && uv sync && uv run spider-body --config config/robot.sim.yaml --sim) &
cd brain && uv sync && uv run spider-brain teleop
```

## Tests

```bash
for p in common body gateway voice brain; do (cd $p && uv sync && uv run pytest -q); done
```
