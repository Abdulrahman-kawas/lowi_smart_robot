OPENING = """# Spider robot: execution plan

Written for a coding agent that has no memory of this project. Every design decision has already
been made. Your job is to run the steps below exactly.

## Rules for the executor

1. Follow the steps in order. Never skip a step.
2. Change nothing that a step does not list. Never improvise, refactor, upgrade, reformat or "improve".
3. Never skip a verification. If a command's output does not match the expected output, or anything
   fails, **stop at once** and report the step ID and the exact output. Do not try to fix it.
4. Timings such as `in 3.21s` or `in 4ms` may differ, and a `2 warnings` in a test summary may come
   and go. Everything else must match.
5. Commit messages are exactly as written, plain, with no AI attribution or co-author line of any kind.
6. Do not switch branches. Do not use `git stash` or worktrees.
7. Read one step at a time, using the line ranges in the index below. You need only this file.
   Mentions of `01_SYSTEM_DESIGN.md` inside a HUMAN STEP are for the owner.
8. To resume in a new session, read `spider-robot/docs/plan/PROGRESS.md`. Its last line is the last
   finished step. Continue with the next step in the index. Every step, including P and Q, adds a line.
9. Run commands from the directory the step names. "Repository root" is the folder that holds `.git`
   and `spider-robot/`.
10. Secrets are placeholders of the form `REPLACE_...`. Never invent a value, and never commit one.
    `VALUE_FROM_THE_OWNER` in a command means: put the value the owner gave you there before you run
    that line. Those host names and users go in `spider-robot/docs/plan/SITE.env`, created in P01.
11. A block headed **HUMAN STEP** is not yours to do. Stop, show the block to the owner, and wait
    until the owner says it is finished and gives you the result to record. Then run the step's
    "When finished" commands, replacing the line `OWNER_RESULT_TEXT` with the owner's text.
    In a step with both a block and Commands, do them in the order they appear.
12. **You never start robot motion on real hardware.** Starting `spider-body`, powering servos, or
    sending any motion command on the real robot is always a HUMAN STEP.

## Before you start, on the Mac

You need `git` with a user name and e-mail configured, `python3`, `rsync`, `uv` version 0.12.17 and
internet access (uv downloads packages). S00 checks the first and last of these. Which Python
interpreter uv picks does not matter here.

Steps S00 to S23 run on the Mac and were rehearsed. Every step whose ID starts with `P` or `Q` needs
the Pi, the server or the robot and is **NOT VALIDATED**: expect to stop and report more often there.
""".split("\n")


def step(sid, title, ms, machine, directory, goal, pre, files, commands, expected, rollback, stop, msg=None,
         human=None, human_first=True, results=False, record=True):
    msg = msg or f"Record that {sid} is done"
    block = []
    if human:
        block += ["> **HUMAN STEP. Executor: stop here, show this block to the owner, and wait.**", ">"]
        block += [f"> {line}" if line else ">" for line in human]
        block += [""]
    cmds = ["- **Commands**, from the repository root on the Mac unless a line uses `ssh`:", "", "```bash", *commands, "```", ""] if commands else []
    out = [f"<!-- BEGIN-STEP {sid} -->", f"## {sid}: {title}", "",
           f"- **Milestone:** {ms}. **Machine:** {machine}. **Directory:** {directory}. **Status:** NOT VALIDATED.",
           f"- **Goal:** {goal}", f"- **Preconditions:** {pre}", f"- **Files touched:** {files}", ""]
    out += (block + cmds) if human_first else (cmds + block)
    out += [f"- **Expected output:** {expected}", f"- **Roll back:** {rollback}",
            f"- **Stop if:** {stop} Report the step ID and the exact output.",
            f"- **Commit message:** `{msg}`", ""]
    if record:
        out += ["- **When finished**, on the Mac, from the repository root:", "", "```bash"]
        if results:
            out += [f"printf '## {sid}, %s\\n\\n' \"$(date +%F)\" >> spider-robot/docs/plan/BENCH_RESULTS.md",
                    "cat >> spider-robot/docs/plan/BENCH_RESULTS.md <<'RESULTS_EOF'", "OWNER_RESULT_TEXT", "RESULTS_EOF"]
        out += [f"printf '%s\\n' '{sid} done' >> spider-robot/docs/plan/PROGRESS.md", "git add -A spider-robot", f'git commit -q -m "{msg}"', "```", ""]
    out += [f"<!-- END-STEP {sid} -->", ""]
    return out


RESULTS = "Give the executor the results as text."
SITE = ". spider-robot/docs/plan/SITE.env"
PROGRESS = lambda s, m: [f"printf '%s\\n' '{s} done' >> spider-robot/docs/plan/PROGRESS.md",
                         "git add -A spider-robot", f'git commit -q -m "{m}"']

ACL_TEST = r'''#!/usr/bin/env bash
# Run on the Pi. Prints FORBIDDEN-DELIVERED for any publish the broker wrongly let through.
set -uo pipefail
R=spider-01
pw() { sudo cat "/etc/spider/secrets/$1.mqtt"; }
sub() { timeout 8 mosquitto_sub -h 127.0.0.1 -p 1883 -u spider-gateway -P "$(pw spider-gateway)" -t "spider/$R/gw/+/cmd" -v > /tmp/acl_gw.txt & 
        timeout 8 mosquitto_sub -h 127.0.0.1 -p 1883 -u spider-camera -P "$(pw spider-camera)" -t "spider/$R/cmd" -v > /tmp/acl_cmd.txt & }
sub
sleep 1
for user in spider-voice spider-camera spider-recorder spider-sysmon spider-console spider-button "$R"; do
  mosquitto_pub -h 127.0.0.1 -p 1883 -u "$user" -P "$(pw "$user")" -q 1 -t "spider/$R/cmd" -m "forbidden-$user" || true
done
for pair in spider-voice:remote spider-voice:planner spider-console:voice spider-button:voice spider-camera:voice; do
  user=${pair%%:*}; source=${pair##*:}
  mosquitto_pub -h 127.0.0.1 -p 1883 -u "$user" -P "$(pw "$user")" -q 1 -t "spider/$R/gw/$source/cmd" -m "forbidden-$user-$source" || true
done
mosquitto_pub -h 127.0.0.1 -p 1883 -u spider-voice -P "$(pw spider-voice)" -q 1 -t "spider/$R/gw/voice/cmd" -m allowed-voice
sleep 2
wait
grep -h forbidden /tmp/acl_gw.txt /tmp/acl_cmd.txt | sed 's/^/FORBIDDEN-DELIVERED /'
grep -h allowed-voice /tmp/acl_gw.txt | sed 's/^/ALLOWED-DELIVERED /'
echo acl-test-finished'''.split("\n")

HARDWARE_STEPS = []
H = HARDWARE_STEPS

H += step("P01", "Prepare the Pi", "M2", "Pi (owner), then Mac", "repository root on the Mac",
  "Pi OS installed, reachable by SSH, on the tailnet, with cooling fitted, and its names recorded.",
  "S23 is done.", "`spider-robot/docs/plan/SITE.env`",
  ["cat > spider-robot/docs/plan/SITE.env <<'SITE_EOF'",
   "PI_USER=VALUE_FROM_THE_OWNER", "PI_HOST=VALUE_FROM_THE_OWNER", "PI_TAILSCALE_NAME=VALUE_FROM_THE_OWNER", "PI_TAILSCALE_IP=VALUE_FROM_THE_OWNER",
   "SITE_EOF", SITE, 'ssh -o BatchMode=yes "$PI_USER@$PI_HOST" uname -m'],
  "the last line is `aarch64`.", "re-image the SD card.",
  "the owner cannot reach the Pi over SSH, or the owner reports a CSI camera (the plan does not cover it).",
  human=["1. Flash Raspberry Pi OS Lite 64-bit with Raspberry Pi Imager. Enable SSH with your key, and Wi-Fi.",
         "2. Fit a heatsink and fan. Without them, assume thermal throttling.",
         "3. Boot, then install Tailscale and join the tailnet: `curl -fsSL https://tailscale.com/install.sh | sh`, `sudo tailscale up`.",
         "4. In the Tailscale admin console apply the ACL in `01_SYSTEM_DESIGN.md` section 7. Tag the Pi `tag:robot`.",
         "5. Keep servo power disconnected until step P08.",
         "6. Check the camera is USB. The plan assumes the `opencv` backend. A CSI module needs `picamera2`, which this install does not provide: tell the executor, and the plan stops here until you decide.",
         "7. Give the executor four values: SSH user, a host name reachable from the Mac, the Tailscale machine name, and `tailscale ip -4`. The executor puts them in `SITE.env` in place of `VALUE_FROM_THE_OWNER`."])

H += step("P02", "Install the software on the Pi", "M2", "Mac, then Pi over SSH", "repository root on the Mac",
  "Install all services. Nothing that can move the robot is enabled.",
  "P01 is done. Servo power is disconnected.",
  "on the Pi only: packages, `/opt/spider`, `/etc/spider`, `/etc/mosquitto/spider`, systemd units",
  [SITE,
   'rsync -a --exclude .venv --exclude __pycache__ --exclude /spider-robot/docs spider-robot "$PI_USER@$PI_HOST:"',
   'ssh -t "$PI_USER@$PI_HOST" \'bash ~/spider-robot/infra/pi/setup_pi.sh\'',
   'ssh "$PI_USER@$PI_HOST" \'systemctl is-enabled spider-body || true; systemctl is-enabled spider-gateway mosquitto ollama spider-tune; systemctl is-active mosquitto; ss -ltn | grep -c 8883 || true\'',
   'ssh -t "$PI_USER@$PI_HOST" \'sudo reboot\' || true',
   'sleep 30; until ssh -o ConnectTimeout=5 "$PI_USER@$PI_HOST" true; do sleep 5; done; echo back'],
  "`setup_pi.sh` ends with `Installed. Reboot once...`. Then one line each: `disabled` (spider-body), `enabled` four times, `active`, `0` (port 8883 is not listening yet). The last line is `back`.",
  "re-image the SD card and repeat from P01.", "the script exits non-zero, or `spider-body` is enabled.")

H += step("P03", "Certificates for the Tailscale listener", "M2", "Mac, then Pi", "repository root on the Mac",
  "Create the private CA and the broker's server certificate, then add the Tailscale listener. Local control uses passwords and needs no certificate.",
  "P02 is done. `/etc/mosquitto/spider` was created by `setup_pi.sh`.",
  "`spider-robot/infra/local/local-certs/` on the Mac, git-ignored; `/etc/mosquitto/spider` on the Pi",
  [SITE,
   '(cd spider-robot/infra/local && BROKER_HOST="$PI_TAILSCALE_NAME" BROKER_IP="$PI_TAILSCALE_IP" bash make_local_certs.sh)',
   '(cd spider-robot/infra/local/local-certs && scp ca.crt server.crt server.key "$PI_USER@$PI_HOST:/tmp/")',
   'ssh -t "$PI_USER@$PI_HOST" \'sudo install -m 640 -o root -g mosquitto /tmp/ca.crt /tmp/server.crt /tmp/server.key /etc/mosquitto/spider/ && rm /tmp/ca.crt /tmp/server.crt /tmp/server.key && sudo install -m 644 ~/spider-robot/infra/local/mosquitto-tls.conf /etc/mosquitto/conf.d/z-spider-tls.conf && sudo systemctl restart mosquitto && systemctl is-active mosquitto && ss -ltn | grep -c 8883\''],
  "the last two lines are `active` and a number of at least `1`.",
  "`ssh` to the Pi, `sudo rm /etc/mosquitto/conf.d/z-spider-tls.conf; sudo systemctl restart mosquitto`, then delete `local-certs/` on the Mac.",
  "Mosquitto is not `active`: a bad certificate file stops the whole broker, loopback included, so use the roll back at once. Do not copy `ca.key` to any machine.")

H += step("P04", "Set the robot configuration", "M2", "Pi over SSH", "repository root on the Mac",
  "Point the config at the real servo port.", "P03 is done. The SSC-32U is plugged into the Pi by USB.", "`/etc/spider/robot.yaml` on the Pi",
  [SITE,
   'SSC=$(ssh "$PI_USER@$PI_HOST" \'ls -1 /dev/serial/by-id/\'); echo "$SSC"; [ "$(printf \'%s\\n\' "$SSC" | wc -l | tr -d \' \')" = 1 ] && [ -n "$SSC" ] || { echo STOP-not-exactly-one-device; exit 1; }',
   'ssh "$PI_USER@$PI_HOST" "sudo -u spider sed -i \'/^ssc:/,/^[a-z]/ s#^  port: .*#  port: /dev/serial/by-id/$SSC#\' /etc/spider/robot.yaml && grep -A1 \'^ssc:\' /etc/spider/robot.yaml"'],
  "one device path, then `ssc:` and a `port:` line holding that `/dev/serial/by-id/` path.",
  "on the Pi, `sudo install -o spider -g spider -m 640 ~/spider-robot/body/config/robot.example.yaml /etc/spider/robot.yaml`.",
  "`STOP-not-exactly-one-device` prints.")

H += step("P05", "Commission the LiDAR and decide the mount (HW1)", "M2", "Pi and robot (owner)", "n/a",
  "Enable the IMU, choose NEGA, verify data, record warm-up, and decide the mount from real objects.",
  "P04 is done. Servo power is disconnected.", "the L2's stored work mode; `BENCH_RESULTS.md`",
  [], "the owner reports results for each item.",
  "set the previous work mode the same way and power-cycle the L2.",
  "`roll_deg` stays null after provisioning.",
  "Record HW1 LiDAR commissioning results", results=True,
  human=["The L2 manual contradicts itself and the SDK on factory defaults, so check rather than assume.",
         "1. Read the work-mode bit meanings in `/opt/spider/unilidar_sdk2/unitree_lidar_sdk/include/unitree_lidar_sdk.h` and the SDK README at the pinned commit. Expected, unverified: bit 0 wide FOV (NEGA), bit 1 2D, bit 2 IMU off, bit 3 serial, bit 4 wait for start. Decide `<value>`: 0 is IMU on, standard FOV; 1 is IMU on, NEGA, if that bit order holds.",
         "2. `sudo systemctl stop spider-lidar`, then `sudo -u spider env ZMQ_ENDPOINT=ipc:///tmp/spider_provision.ipc ZMQ_RECORD_ENDPOINT= LIDAR_SET_WORK_MODE=<value> /opt/spider/bin/lidar_bridge`. Run it only with the service stopped, and as `spider`, so it cannot leave a root-owned socket behind. Power-cycle the L2.",
         "3. `sudo systemctl start spider-lidar`. Note the time from cold power-on to the first cloud: below 30 C the L2 self-heats before sending any.",
         "4. With servo power disconnected, `sudo systemctl start spider-body`, then read `roll_deg`: `sudo -u spider sh -c 'mosquitto_sub -h 127.0.0.1 -p 1883 -u spider-console -P \"$(cat /etc/spider/secrets/spider-console.mqtt)\" -t spider/spider-01/state -C 1'`. It must not be null. `sudo systemctl stop spider-body`. Log an azimuth histogram per cloud.",
         "5. Place a 5 cm box, then a 2.5 cm pipe, at 0.5 m in at least 8 bearings. Record for each whether the sector map shows it. Upright in normal mode nothing below the sensor plane is seen.",
         "6. Decide the mount (design section 6.2, H-02). Inverted on a mast is recommended; set `imu_upside_down: true` for it.",
         "7. " + RESULTS])

H += step("P06", "Real-time gate RT1, the most important gate in the plan", "M2", "Pi (owner)", "`/opt/spider/spider-robot/infra/pi` on the Pi",
  "Prove the control loop holds under full AI load, with FIFO and mlock off and then on.",
  "P05 is done.", "`/tmp/robot-nort.yaml` on the Pi; `BENCH_RESULTS.md`",
  [], "the second run (the shipped setting): `late_ms.p999_ms` ≤ 5, `max_ms` ≤ 18, `overruns` ≤ 1 per 10,000 ticks, `rt_ok` true; Core 0 at most 40% average; `cyclictest` max at most 2 ms.",
  "none needed: the test changes nothing.",
  "the shipped setting misses a limit. Do not go on: the remedy order in the design's section 12 needs the owner.",
  "Record RT1 control loop timing", results=True,
  human=["The script below starts `spider-body`, so the owner runs it and the executor does not. Each run takes an hour. **First confirm servo power is physically disconnected.**",
         "1. Start a `tmux` session, so the runs survive a dropped SSH connection.",
         "2. `/opt/spider/spider-robot/body/.venv/bin/python -c \"import yaml; d = yaml.safe_load(open('/etc/spider/robot.yaml')); d['rt'] = {'enabled': False}; yaml.safe_dump(d, open('/tmp/robot-nort.yaml', 'w'))\"`",
         "3. First run, FIFO and mlock off: `sudo bash bench_jitter.sh 3600 /tmp/robot-nort.yaml`",
         "4. Second run, the shipped setting: `sudo bash bench_jitter.sh 3600 /etc/spider/robot.yaml`. Each run prints one JSON line.",
         "5. During the second run, record Core 0 load (`mpstat -P 0 5`) and a `/proc/interrupts` diff, which also shows the camera's interrupt rate. Limits: Core 0 at most 40% average, `cyclictest -a 0 -p 80 -m -D 1h` max at most 2 ms.",
         "6. " + RESULTS])

H += step("P07", "Broker gate NET5, no-network boot and fault tests with servos unpowered", "M2", "Pi over SSH, then owner", "repository root on the Mac",
  "Prove the ACL on the real broker, that the Pi works with no network and a wrong clock, and FI1-FI5.",
  "P06 passed. Servo power is **disconnected**.",
  "`/tmp/acl_test.sh` on the Pi; `BENCH_RESULTS.md`",
  [SITE,
   'ssh "$PI_USER@$PI_HOST" \'cat > /tmp/acl_test.sh\' <<\'ACL_EOF\'', *ACL_TEST, "ACL_EOF",
   'ssh "$PI_USER@$PI_HOST" \'sudo systemctl stop spider-gateway; bash /tmp/acl_test.sh; sudo systemctl start spider-gateway; systemd-analyze critical-chain spider-gateway.service | head -20\''],
  "an `ALLOWED-DELIVERED` line, no `FORBIDDEN-DELIVERED` line, then `acl-test-finished`. The critical chain shows no `network-online.target`.",
  "`ssh` to the Pi and `sudo systemctl start spider-gateway`.",
  "any `FORBIDDEN-DELIVERED` line appears, `ALLOWED-DELIVERED` does not appear, or the chain includes `network-online.target`.",
  "Record broker ACL and no-network boot results", results=True, human_first=False,
  human=["After the executor's commands above, with servo power still disconnected:",
         "1. B-F1: Wi-Fi off, Pi clock at 2000-01-01 (`sudo timedatectl set-ntp false; sudo date -s 2000-01-01`). Reboot. All local services must connect and a Stop must reach the body. Voice-side services come up in 90 s. Restore with `sudo timedatectl set-ntp true`.",
         "2. FI1 to FI5 (design section 9.5): `kill -9` spider-body restarts within 5 s and relaxes; `kill -STOP` is killed and restarted within 2 s; `kill -9` lidar_bridge means no motion within 0.5 s; `kill -9` spider-gateway and `systemctl stop mosquitto` each stop motion within 1.5 s.",
         "3. B-F2: 20 hard power cuts, boots every time.",
         "4. " + RESULTS])

H += step("P08", "First servo motion on a stand", "M3", "Pi and robot (owner)", "any directory on the Pi",
  "Calibrate and run first motion safely.", "P07 passed.", "`/etc/spider/calibration.yaml`, `robot.yaml`, `gateway.env`; `BENCH_RESULTS.md`",
  [], "the owner reports the pass criteria in the block above.",
  "cut servo power; `sudo systemctl disable --now spider-body`.",
  "anything moves unexpectedly. Cut power first.",
  "Record first powered motion results", results=True,
  human=["**The executor must not do any part of this.** Robot on a stand with all feet off the ground. Owner present. A tested way to cut servo power within reach.",
         "1. Connect servo power with the switch off. Test the cut-off once.",
         "2. With `spider-body` stopped: `sudo -u spider /opt/spider/spider-robot/body/.venv/bin/spider-calibrate --config /etc/spider/robot.yaml check`, then the same with `center`, `trim`, `direction`.",
         "3. In `/etc/spider/robot.yaml` set `require_lidar: false`, only for this stand work. In `/etc/spider/gateway.env` set `SG_BENCH=1`. `sudo systemctl restart spider-gateway`.",
         "4. `sudo systemctl start spider-body`, then `spider-robotctl status`.",
         "5. `spider-robotctl bench stand`. Each leg must wake in turn, nothing snaps, the Pi does not reset (B6).",
         "6. RT2, 30 min in the air: `spider-robotctl bench walk --vx 0.06 --seconds 60`, repeated, with overruns at most 1 per 10,000 ticks. HW2 part one: `spider-robotctl bench sit`, `bench relax`, and record whether torque goes away. B1: logic analyser shows no group-move gap over 45 ms. FI1, FI2, FI9 powered: no jump on any restart, and the process exits after 0.5 s on a pulled USB cable.",
         "7. `spider-robotctl stop`. Restore `require_lidar: true`. Leave `SG_BENCH=1` for P09.",
         "8. " + RESULTS])

H += step("P09", "Physical E-stop, watchdog relay, release button, floor reflex", "M4", "robot (owner)", "any directory on the Pi",
  "Fit the only true Category 0 stop, and the network-free release.", "P08 passed.", "robot wiring; `/etc/spider/robot.yaml`, `gateway.env`; `BENCH_RESULTS.md`",
  [], "the owner reports the pass criteria in the block above.",
  "disconnect the relay board and remove `watchdog_gpio` from `robot.yaml`.",
  "any gate fails. **No untethered walking before this step passes.**",
  "Record physical E-stop and floor reflex results", results=True,
  human=["Parts: mushroom-head twist-release NC switch, relay, retriggerable timer, momentary button, battery fuse, low-voltage buzzer, separate Pi regulator. Measure current first (item 4) to size the relay and fuse.",
         "1. Fit the switch and relay upstream of both UBECs. Fit the fuse and alarm. Put the Pi on its own regulator.",
         "2. Fit the timer on GPIO 17 and add `watchdog_gpio: {chip: /dev/gpiochip0, line: 17}` to `/etc/spider/robot.yaml`.",
         "3. Wire the button from GPIO 27 to ground. `sudo systemctl enable --now spider-button`.",
         "4. HW2: switch to servo-power-off within 20 ms on a scope. HW3: relay drops within 200 ms when toggling stops. HW4: clamp meter walking and at stall; size relay and fuse from it. HW5: below 80 C after 30 min full AI load with the fan, and sysmon reports an undervoltage. Fit the LiDAR mount decided in P05.",
         "5. B-E1: latch an E-stop, Wi-Fi off, reboot, release by a 3 s hold. A short press must not release.",
         "6. RT3 on the floor with someone at the E-stop: `spider-robotctl bench stand`, then `spider-robotctl bench walk --vx 0.12 --seconds 10` toward a box 1 m away, 20 runs. It must stop with at least 10 cm remaining, every run.",
         "7. Set `SG_BENCH=0` in `/etc/spider/gateway.env` and `sudo systemctl restart spider-gateway`. The bench source must not stay on.",
         "8. " + RESULTS])

H += step("P10", "Voice benches and enabling voice", "M5", "Pi over SSH, then owner", "repository root on the Mac",
  "Replace every voice estimate with a measurement and set the voice limits.", "P09 passed.",
  "`/etc/spider/voice.yaml` on the Pi; `BENCH_RESULTS.md`",
  [SITE,
   'ssh "$PI_USER@$PI_HOST" \'sudo systemctl enable --now spider-camera spider-recorder; /opt/spider/spider-robot/voice/.venv/bin/spider-voice-bench --help | head -3\''],
  "the first lines of the help text print. Bench figures come from the owner's runs.",
  "`ssh` to the Pi and `sudo systemctl disable --now spider-voice`.",
  "any false motion in V2, or stop recall below target. The next rung is the `base` model instead of `tiny`, then a trained keyword spotter; it needs the owner.",
  "Record voice bench results", results=True, human_first=False,
  human=["After the executor's command above. The bench tool does not connect to the broker, so it cannot move the robot.",
         "1. Record the corpus: 200 owner utterances, 16 kHz mono, with a manifest of `{\"wav\", \"text\", \"act\"}` lines.",
         "2. V1 and B-V1: `spider-voice-bench --config /etc/spider/voice.yaml --manifest corpus.jsonl --out v1.json`. Also check `chunk_length` for short windows.",
         "3. S1: 100 Arabic prompts; at least 98% valid JSON and none truncated.",
         "4. Set `max_motion_age_s` to the STT p95 plus 2 s. Set `stt.whisper_local.timeout_s` to at least twice the slowest STT seen, and never under 20. If p95 is over 2.5 s, you may set `stt.primary: whisper_server` after Q03.",
         "5. Enable voice: `sudo systemctl enable --now spider-voice`. Wait for `spider-voice ready` in the log.",
         "6. With the robot on a stand first: V2 stop recall at least 95% quiet and 85% with gait noise, zero false motion in 30 min of TV audio. V3: the robot never acts on its own voice. V4: speech-onset stop stays off unless false stops are at most 1 per 5 min of walking. V5: voice ready within 90 s with nothing connected. FI6, FI7.",
         "7. " + RESULTS])

H += step("Q01", "Install the home server", "M6", "Mac, then server over SSH", "repository root on the Mac",
  "Install the brain and local models.", "P10 passed. The owner has joined the server to the tailnet, tagged `tag:server`, and given its SSH user and host.",
  "`SITE.env`; on the server only",
  ["printf 'SERVER_USER=%s\\nSERVER_HOST=%s\\n' VALUE_FROM_THE_OWNER VALUE_FROM_THE_OWNER >> spider-robot/docs/plan/SITE.env", SITE,
   'rsync -a --exclude .venv --exclude __pycache__ --exclude /spider-robot/docs spider-robot "$SERVER_USER@$SERVER_HOST:"',
   'ssh -t "$SERVER_USER@$SERVER_HOST" \'bash ~/spider-robot/infra/server/setup_server.sh\'',
   'ssh "$SERVER_USER@$SERVER_HOST" \'for p in 8080 8081; do for i in $(seq 1 60); do curl -fs http://127.0.0.1:$p/health && break; sleep 30; done; echo; done\''],
  "`{\"status\":\"ok\"}` twice. The models download first, which can take up to 30 minutes each.",
  "on the server, `sudo systemctl disable --now llama-vision llama-planner`.",
  "the script fails, or either health line is empty.")

H += step("Q02", "Server secrets and first connection", "M6", "Mac, server and Pi (owner)", "n/a",
  "Give the brain its certificate and secrets, then connect it.", "Q01 is done.",
  "`/etc/spider-brain/brain.env`, `secrets.env`, `certs/` on the server",
  [], "the owner reports `spider-brain` active and the dashboard reachable.",
  "on the server, `sudo systemctl disable --now spider-brain`.", "the brain cannot connect to the broker.",
  human=["1. Copy `ca.crt`, `spider-brain.crt`, `spider-brain.key` from `spider-robot/infra/local/local-certs/` on the Mac to `/etc/spider-brain/certs/` on the server, mode 600.",
         "2. On the server, in `/etc/spider-brain/brain.env`, replace `REPLACE_WITH_PI_TAILSCALE_NAME`, `REPLACE_WITH_TELEGRAM_USER_ID` and `REPLACE_WITH_SPIDER_AT_PI_TAILSCALE_NAME` (an SSH target such as `spider@spider-pi`).",
         "3. On the server, in `/etc/spider-brain/secrets.env`, put `SB_TELEGRAM_TOKEN=` and any API keys. Mode 600.",
         "4. Turn on two-step verification on the Telegram account: it is effectively the robot's key.",
         "5. On the Pi, set `sysmon.server_tailscale_name` in `/etc/spider/robot.yaml` to the server's Tailscale machine name and `sudo systemctl restart spider-sysmon`.",
         "6. On the server: `sudo systemctl enable --now spider-brain`, then `sudo tailscale serve --bg 8765` (8765 is the dashboard's default port).",
         "7. Tell the executor it is done."])

H += step("Q03", "Remote control gates", "M6", "phone, server, Pi (owner)", "n/a",
  "Prove remote control, its caps, the release flow, vision and the soak.", "Q02 is done.", "`BENCH_RESULTS.md`",
  [], "the owner reports each item.",
  "on the server, `sudo systemctl stop spider-brain`.", "the owner reports that a release succeeded with a reused confirmation.",
  "Record remote control and soak results", results=True,
  human=["1. NET1 and B-N1: `tailscale ping` shows a direct path. 50 Telegram Stops timed by video, p95 at most 300 ms after the server receives each.",
         "2. NET2: `sudo tc qdisc add dev tailscale0 root netem delay 300ms 100ms loss 5%` on the server, then pull Wi-Fi during a remote walk, with someone at the E-stop. Motion must end by itself within 1.75 s. Remove with `sudo tc qdisc del dev tailscale0 root`.",
         "3. NET3 (server off: voice unaffected, console works over SSH), NET4 (WAN blocked), FI8, FI10.",
         "4. Remote release: it works once, and is refused when the same confirmation is sent again.",
         "5. V6: time one image through `llama-server`, then try Ollama and record whether it loads the projector. Set `SB_VISION_TIMEOUT_S` to the p95 plus 50%.",
         "6. Optional cloud: set `SB_ASK_FALLBACK=compat:moonshotai/kimi-k3`. `kimi-k3.1-pro` had no API on 2026-11-04; check NVIDIA's page before switching.",
         "7. S2 and B-S2: 24 h soak; no restart, memory flat within 10%.",
         "8. " + RESULTS])

H += step("Q04", "Recording, SLAM and the on-demand AWS worker", "M7", "server, AWS (owner)", "n/a",
  "Prove recording, mapping and that the worker stops itself.", "Q03 passed.", "AWS account; `BENCH_RESULTS.md`",
  [], "the owner reports each gate item.",
  "`aws ec2 stop-instances --instance-ids <id>`.", "the worker does not stop itself with the link home cut.",
  "Record mapping and AWS worker results", results=True,
  human=["1. **Before anything else** create the budget alarm: `ACCOUNT_ID=<yours> EMAIL=<yours> LIMIT_USD=20 bash spider-robot/infra/aws/worker/budget_alarm.sh`.",
         "2. Create one c7i.2xlarge instance, join it to the tailnet tagged `tag:worker`, run `worker_setup.sh` on it, set instance-initiated shutdown to `stop`, then stop it. Apply `worker-control-policy.json` to a user whose keys live only on the server.",
         "3. Set `SB_AWS_WORKER_INSTANCE_ID` and `SB_AWS_WORKER_SSH_TARGET` in `brain.env`. Restart the brain.",
         "4. `/record 120` in Telegram. Cut power mid-job once and confirm the file is readable to its last frame.",
         "5. `/map <job id>`. Judge whether the map is usable.",
         "6. Start a job, cut the link home, confirm the instance stops itself within 15 idle minutes and the 4 h maximum.",
         "7. " + RESULTS])

H += step("Q05", "Clean up old AWS IoT and EC2 files", "M8", "Mac", "repository root",
  "Delete files the home server has replaced, as agreed.", "The owner has told you M6 has run for two weeks with no unexplained restart, and has approved this deletion. Do not run this step without that message.",
  "`spider-robot/infra/ec2/`, `spider-robot/infra/aws/iot_setup.sh`, `body-policy.json`, `brain-policy.json`",
  ["git rm -r -q spider-robot/infra/ec2 spider-robot/infra/aws/iot_setup.sh spider-robot/infra/aws/body-policy.json spider-robot/infra/aws/brain-policy.json",
   *PROGRESS("Q05", "Remove the EC2 and AWS IoT files replaced by the home server")],
  "no output.", "`git revert --no-edit HEAD`.", "`git rm` reports a missing path.",
  "Remove the EC2 and AWS IoT files replaced by the home server", record=False)
