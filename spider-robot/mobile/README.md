# Lowi mobile app

One universal SwiftUI app for iPhone and iPad: the robot's camera, dead-man driving, photos and
E-stop. The app talks only to the brain on the home server, over Tailscale. It never speaks MQTT
and never connects to the Pi. Everything it does goes out as the gateway's `remote` source, so
the remote caps (0.05 m/s, 0.3 rad/s, moves of at most 1 s) and the body's own limits apply.

| Part | Where | State |
|---|---|---|
| Brain API (`/v1`) | `brain/src/spider_brain/mobile/` | built, tested against the simulator |
| iOS and iPadOS app | `mobile/ios/` | to build |

## Run everything on a Mac, without hardware

Four terminals, all from `spider-robot/`. Install the tools once:

```bash
brew install mosquitto xcodegen
```

1. Broker, plain MQTT on `127.0.0.1:1884` (simulator only):

   ```bash
   /opt/homebrew/sbin/mosquitto -c infra/local/mosquitto-sim.conf
   ```

2. Simulated body. Its camera returns a grey frame with an orange box and a clock:

   ```bash
   (cd body && uv run spider-body --config config/robot.sim.yaml --sim --text-logs)
   ```

3. Command gateway, on the same broker by default:

   ```bash
   (cd gateway && uv run spider-gateway)
   ```

4. Brain with the mobile API. `SB_ENV_FILE=/dev/null` keeps a real `.env` (Telegram token, API
   keys) out of a simulator run:

   ```bash
   cd brain
   export SB_ENV_FILE=/dev/null SB_ROBOT_SOURCE=planner SB_HUMAN_SOURCE=remote SB_MOBILE=1 \
          SB_MOBILE_DATA_DIR=/tmp/lowi-sim-mobile
   uv run spider-brain serve
   ```

   It prints `Mobile API: http://127.0.0.1:8765/v1`.

5. Pair. In another terminal with the same four `export`s:

   ```bash
   cd brain && uv run spider-brain pair      # prints a 6-digit code, valid once for 2 minutes
   uv run spider-brain devices list
   uv run spider-brain devices revoke "Simulator iPhone"
   ```

In the iOS Simulator, use `127.0.0.1` as the brain address and the code from step 5.

## On the home server

```bash
# In /etc/spider-brain/brain.env: SB_MOBILE=true, SB_MOBILE_DATA_DIR=/var/lib/spider-brain/mobile
sudo systemctl restart spider-brain
sudo tailscale serve --bg 8765          # the dashboard and /v1 share this port

# Pair, as the service user and with the service's environment. systemd-run loads secrets.env
# (root-only) the way the service does, so the code is also sent to you on Telegram.
sudo systemd-run --quiet --pipe --wait --uid="$(systemctl show -p User --value spider-brain)" \
  -p EnvironmentFile=/etc/spider-brain/secrets.env -E SB_ENV_FILE=/etc/spider-brain/brain.env \
  "$(systemctl show -p WorkingDirectory --value spider-brain)/.venv/bin/spider-brain" pair
```

`devices list` and `devices revoke <name>` work the same way; they need no Telegram token.

The phone needs the Tailscale app switched on. The brain address is the server's MagicDNS name,
for example `home-server.<tailnet>.ts.net`; `tailscale serve` gives it HTTPS. HTTPS
certificates must be enabled for the tailnet in the Tailscale admin console.

## API

Every route but `/v1/hello` and `/v1/pair` needs `Authorization: Bearer <device token>`.

| Route | Does |
|---|---|
| `GET /v1/hello` | `{service, api}`: connection test before pairing |
| `POST /v1/pair {code, device_name}` | `{token, device_name, robot_id, caps}`. One attempt per second; a code dies after 5 wrong tries |
| `GET /v1/state` | robot state (no LiDAR), gateway owner and E-stop, drive holder, latency, frame age, caps |
| `POST /v1/stop`, `POST /v1/estop` | HTTP fallback when the socket is down |
| `POST /v1/estop/release` | starts a confirmation: `{challenge_id, action, frame_jpeg, frame_age_ms, ttl_s}` |
| `POST /v1/wake {posture}` | the same, to stand or sit a limp robot (`wake_from_limp`) |
| `POST /v1/confirm {challenge_id, approved}` | finishes it once, only from the phone that started it: `released`, `posture_sent`, `cancelled` or `refused` |
| `POST /v1/photo {question?}` | `{frame_jpeg, answer, vision_error}` |
| `WS /v1/live` | first message `{"type":"auth","token":…}` within 5 s, else close 4401 |

On `/v1/live`:

- **Server to app:** `hello`, `state` (each new robot state, 4 Hz from the body, and at least
  once a second), `lidar` (36 sectors), `event` (`kind`, `detail`, `level`, `refusal`), `pong`.
  Frames are binary: `[u32 big-endian header length][header JSON {type, n, age_ms}][JPEG]`.
- **App to server:** `drive {x, y, turn, hold_id}`, `stop`, `estop`,
  `posture {stand|sit|relax}`, `video {on}`, and `heartbeat {t}` every second. The server treats
  3 s of silence as a lost socket.
- **Drive inputs:** each from -1 to 1. `x` is forward, `y` is left, and `turn` is positive to the
  left. The brain scales them to the caps.

Frame age is measured on the brain from the moment it asked for the frame, so it is an upper
bound that needs no clock sync. The app adds the time since the frame arrived.

## Dead-man rules

The brain enforces them, whatever the phone does.

- No drive renewal for 0.6 s stops the robot. Measured in the simulator after the last renewal:
  the brain stops at 0.63 s, velocity is zero at 0.83 s, and the legs finish their step at
  1.31 s.
- The driving phone's socket closing stops the robot. A phone that was only watching stops
  nothing.
- Stop or E-stop from any phone stops the robot first, then ends every hold.
- A refusal, preemption or safety stop ends the hold. A stick that is still held does not restart
  the robot; the owner has to lift and press again.
- One phone drives at a time.
- Driving needs a standing robot, telemetry no older than 1.5 s, and a camera frame sent to that
  phone no older than 2 s.

The live view asks for at most one frame every 0.6 s and gives way to photos and confirmation
frames, which share the gateway's one-frame-per-0.5 s allowance. If the robot keeps reporting late
control ticks while the live view runs, the brain halves the frame rate.
