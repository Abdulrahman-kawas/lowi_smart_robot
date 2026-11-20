# Lowi mobile app

One universal SwiftUI app for iPhone and iPad: the robot's camera, dead-man driving, photos and
E-stop. The app talks only to the brain on the home server, over Tailscale. It never speaks MQTT
and never connects to the Pi. Everything it does goes out as the gateway's `remote` source, so
the app's own top speed (set in Settings: 0.05 m/s and 0.3 rad/s until changed, at most the
gateway's ceiling of 0.12 m/s and 0.6 rad/s), moves of at most 1 s and the body's own limits
apply.

| Part | Where | State |
|---|---|---|
| Brain API (`/v1`) | `brain/src/spider_brain/mobile/` | built, tested against the simulator |
| iOS and iPadOS app | `mobile/ios/` | built: iPhone and iPad, keyboard and controller, photo, E-stop release, English and Japanese |

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

6. The app. SwiftUI, iOS and iPadOS 17 or newer, Swift 6, no third-party packages. The
   project is described in `ios/project.yml`; the generated `Lowi.xcodeproj` is not in git.

   ```bash
   cd mobile/ios
   xcodegen generate
   open Lowi.xcodeproj        # run the Lowi scheme on an iPhone simulator
   ```

   In the app, use `127.0.0.1` as the brain address and the code from step 5. To run on a real
   phone, set your team and a bundle id of your own in `project.yml`, then generate again.

### Screens and controls

- **Connect:** brain address, connection test (it says when Tailscale is off on the device),
  pairing code.
- **Drive, iPhone (landscape):** the camera frame in full; the joystick under the left thumb;
  the turn control and STOP under the right; Stand and Sit. The top bar shows the link state,
  latency, frame age, mode, E-stop and the limiter reason.
- **Drive, iPad:** the same camera stage, with a sidebar holding the LiDAR radar (36 sectors,
  nearest obstacle marked), robot state, moves, photo with a question, and the event log. In
  portrait the sidebar moves under the camera.
- **Keyboard:** W/S forward and back, A/D sideways, Q/E turn, Space STOP, Esc E-stop: the keys of
  the simulator page. Keys are ignored while a text field has the keyboard.
- **Game controller:** the left stick drives, the right stick turns, B is STOP, Y is E-stop.
- **Speed (Settings):** the app's top speed (2 to 12 cm/s) and turning speed (10 to 34 °/s),
  kept by the gateway and shown as it reports them, with its ceiling under them; Walking and
  Turning as Slow, Normal or Fast (40, 70 or 100 % of the top speed, with the real cm/s and °/s);
  and the speed of moves. Off while the app has no live link.
- **LiDAR protection (Settings):** on by default. Turning it off needs confirmation, shows a red
  banner on the drive screen and renews a 2 s lease about every 1 s while the app is active. It
  restores on background, link loss, E-stop, an explicit Turn on, lease expiry or disconnect.
  The body still obeys known tilt, joint limits, Stop and E-stop.
- **Moves:** one button for every built-in move, with the leading leg where it applies. The speed
  is Normal, Lively or Fast in Settings; the sheet shows the body's or gateway's own status text.
  Settings can switch moves from the app and from voice on or off for this robot; the sheet greys
  out and points to Settings when app moves are off. The body still refuses any move it cannot do
  safely.
- **Photo:** an iPhone screen of its own, a sidebar panel on iPad. The vision answer is shown
  only; it never moves the robot.
- **E-stop release, and standing a limp robot:** a fresh photo, what will happen, and a long
  press. A confirmation works once.
- **STOP:** on every screen, never disabled, fires on touch-down, and goes out on the socket and
  over HTTP at once.

Holding a finger, a key or a stick is the dead-man hold; touch wins over keys, and keys win
over a controller.

### Languages and accessibility

- **Languages:** English and Japanese, in `Lowi/Resources/Localizable.xcstrings`. Text the robot
  itself sends, such as the limiter reason or a refusal from the gateway, stays in English. To
  add a language or new strings, export, translate the XLIFF, and import:

  ```bash
  xcodebuild -exportLocalizations -project Lowi.xcodeproj -localizationPath build/loc \
    -exportLanguage ja -sdk iphonesimulator
  xcodebuild -importLocalizations -project Lowi.xcodeproj -localizationPath build/loc/ja.xcloc
  ```

- **Right to left:** text and bars follow the language. The joystick, the turn control and STOP
  keep their places, so a thumb finds STOP bottom-right on every screen.
- **Dynamic Type:** everything scales. On the drive screen the text over the camera stops growing
  at the first accessibility size, and the top-bar chips scroll sideways. STOP and the thumb
  controls never leave the screen.
- **VoiceOver:**
  - Every control has a label.
  - Refusals and alerts are announced.
  - The joystick needs a held touch, so VoiceOver users drive with a keyboard or a controller.
- **Haptics:** a firm tap on STOP and E-stop, and a warning on every refusal. They can be turned
  off in Settings.
- **Accessibility audit:** `AccessibilityAuditTests` runs Apple's audit on every screen and fails
  on any issue except the deliberate limits listed in the test, each with its reason.

Tests, from `mobile/ios` (pick any installed iPhone or iPad simulator):

```bash
DEST='platform=iOS Simulator,name=iPhone 15 Pro'   # iOS 17.5; iPhone 17 Pro for iOS 26
xcodebuild -scheme Lowi -destination "$DEST" -only-testing:LowiTests test
xcodebuild -scheme Lowi -destination "$DEST" -collect-test-diagnostics never \
  -only-testing:LowiUITests/StopOnConnectTests -only-testing:LowiUITests/StopEverywhereTests \
  -only-testing:LowiUITests/ProtectionTests -only-testing:LowiUITests/AccessibilityAuditTests test
# Every screen as screenshots (the app's built-in fake brain, debug builds only):
TEST_RUNNER_LOWI_SCREENSHOTS=1 xcodebuild -scheme Lowi -destination "$DEST" \
  -resultBundlePath build/shots.xcresult -only-testing:LowiUITests/ScreenshotTests test
xcrun xcresulttool export attachments --path build/shots.xcresult --output-path build/shots
# End to end against the stack above, with a robot that is limp (restart spider-body) and a
# fresh code from step 5:
TEST_RUNNER_LOWI_PAIR_CODE=123456 xcodebuild -scheme Lowi -destination "$DEST" \
  -collect-test-diagnostics never -only-testing:LowiUITests/SimulatorDriveTests test
```

`-collect-test-diagnostics never`: with Xcode 27.1, a failed UI test otherwise leaves
`xcodebuild` collecting diagnostics without ever exiting.

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
| `GET /v1/state` | robot state (no LiDAR), gateway owner, E-stop, moves switches and the app's speed limit with its ceiling (`remote_limits`, null from an older gateway), drive holder, latency, frame age, caps (the lower of the brain's caps and that limit) |
| `POST /v1/stop`, `POST /v1/estop` | HTTP fallback when the socket is down |
| `POST /v1/estop/release` | starts a confirmation: `{challenge_id, action, frame_jpeg, frame_age_ms, ttl_s}` |
| `POST /v1/wake {posture}` | the same, to stand or sit a limp robot (`wake_from_limp`) |
| `POST /v1/confirm {challenge_id, approved}` | finishes it once, only from the phone that started it: `released`, `posture_sent`, `cancelled` or `refused` |
| `POST /v1/photo {question?}` | `{frame_jpeg, answer, vision_error}` |
| `WS /v1/live` | first message `{"type":"auth","token":…}` within 5 s, else close 4401 |

On `/v1/live`:

- **Server to app:** `hello`, `state` (each new robot state, 4 Hz from the body, and at least
  once a second, including `robot.protection`; missing means on), `lidar` (36 sectors),
  `event` (`kind`, `detail`, `level`, `refusal`), `pong`.
  Frames are binary: `[u32 big-endian header length][header JSON {type, n, age_ms}][JPEG]`.
- **App to server:** `drive {x, y, turn, hold_id, speed?, turn_speed?}`, `stop`, `estop`,
  `look {pan_deg, speed}`, `perform {name, speed, leg?}`,
  `moves_switch {voice?, remote?}`, `speed_limit {max_speed_mps, max_wz_rps}`,
  `protection {enabled, ttl_s}`, `posture {stand|sit|relax}`, `video {on}`, and
  `heartbeat {t}` every second. Drive events (`drive_ended`, `drive_refused`) carry the
  `hold_id` of the press they end. The server treats 3 s of silence as a lost socket.
- **Drive inputs:** each from -1 to 1. `x` is forward, `y` is left, and `turn` is positive to the
  left. The brain scales them to the caps. `speed` and `turn_speed` (0 < f <= 1, missing = 1) are
  the Walking and Turning setting, a fraction of the caps; any other value refuses the press.
- **Speed limit:** `speed_limit` sets the app's top speed in the gateway, which keeps it across
  restarts. The brain refuses it above its own caps; the gateway refuses it above its ceiling.
- **LiDAR protection:** `protection {enabled, ttl_s}` is app-only and forwarded as the `remote`
  source; `ttl_s` is 1-5 seconds, default 2. Turning protection off skips LiDAR freshness,
  obstacle distances and unknown tilt in the body, but never Stop, E-stop, known tilt, joint
  limits or the link watchdog. The app renews off about every 1 s while active; the body restores
  on E-stop, relax, expiry or `enabled: true`, and the brain restores on disconnect when no other
  app owns the off state. Voice, the planner and HTTP cannot send this message.

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
