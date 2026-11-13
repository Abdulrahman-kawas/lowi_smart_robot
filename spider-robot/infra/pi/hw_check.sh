#!/usr/bin/env bash
# First check of a newly plugged camera, microphone and speaker. Run on the Pi:
#   bash ~/spider-robot/infra/pi/hw_check.sh
# Or name the audio devices yourself (names from `arecord -L` and `aplay -L`):
#   MIC=plughw:CARD=X,DEV=0 SPK=plughw:CARD=Headphones,DEV=0 bash ~/spider-robot/infra/pi/hw_check.sh
# It takes one photo, records 4 s, plays it back, and writes the two audio device names into
# /etc/spider/voice.yaml (the old file is kept). It starts no service and moves nothing.
set -uo pipefail
VOICE_CFG=/etc/spider/voice.yaml
BODY_PY=/opt/spider/spider-robot/body/.venv/bin/python
PHOTO=/tmp/spider-camera-test.jpg
WAV=/tmp/spider-mic-test.wav

echo "== Camera"
video=""
for d in /dev/video[0-9]; do  # /dev/video10 and up are the Pi's own codecs, not cameras
  [[ -e "$d" ]] && video="$d" && break
done
if [[ -z "$video" ]]; then
  echo "  no camera: plug the USB camera in and run again"
else
  name="$(cat "/sys/class/video4linux/$(basename "$video")/name" 2>/dev/null)"
  echo "  found $video ($name)"
  sudo "$BODY_PY" - "$video" "$PHOTO" <<'EOF'
import sys, cv2
cap = cv2.VideoCapture(int(sys.argv[1].removeprefix("/dev/video")))
for _ in range(5):  # the first frames are often dark while exposure settles
    ok, frame = cap.read()
cap.release()
if not ok:
    sys.exit("  camera opened but gave no frame")
cv2.imwrite(sys.argv[2], frame)
print(f"  photo saved: {sys.argv[2]} ({frame.shape[1]}x{frame.shape[0]})")
EOF
  [[ "$video" == /dev/video0 ]] || echo "  note: robot.yaml expects device 0; set camera.device to ${video#/dev/video}"
fi

echo "== Microphone and speaker"
echo "  microphones:"; arecord -L | grep -E '^plughw:CARD=' | sed 's/^/    /'
echo "  speakers:";    aplay -L | grep -E '^plughw:CARD=' | grep -v vc4hdmi | sed 's/^/    /'
MIC="${MIC:-$(arecord -L | grep -m1 -E '^plughw:CARD=')}"
# A USB speaker first, then the 3.5 mm jack. HDMI is never chosen.
SPK="${SPK:-$(aplay -L | grep -E '^plughw:CARD=' | grep -vE 'vc4hdmi|Headphones' | head -1)}"
SPK="${SPK:-plughw:CARD=Headphones,DEV=0}"
if [[ -z "$MIC" ]]; then
  echo "  no microphone: plug a USB microphone in and run again"
  exit 1
fi
echo "  using microphone $MIC"
echo "  using speaker    $SPK"

echo "  recording 4 s: speak now..."
arecord -q -D "$MIC" -f S16_LE -r 16000 -c 1 -d 4 "$WAV" || { echo "  recording failed"; exit 1; }
python3 - "$WAV" <<'EOF'
import math, struct, sys, wave
w = wave.open(sys.argv[1]); data = w.readframes(w.getnframes())
samples = struct.unpack(f"<{len(data)//2}h", data)
rms = math.sqrt(sum(s * s for s in samples) / max(1, len(samples)))
db = 20 * math.log10(rms / 32768) if rms else -120.0
verdict = "good" if db > -40 else "quiet: move closer or raise the mic gain in alsamixer"
print(f"  level {db:.0f} dBFS ({verdict}); the voice loop ignores sound below -45 dBFS")
EOF
echo "  playing it back..."
aplay -q -D "$SPK" "$WAV" || echo "  playback failed on $SPK: set SPK=... and run again"

backup="$VOICE_CFG.bak-$(date +%Y%m%d-%H%M%S)"
sudo cp -p "$VOICE_CFG" "$backup"
sudo sed -i -E \
  -e "s#^(  capture_device:).*#\1 \"$MIC\"#" \
  -e "s#^(  playback_device:).*#\1 \"$SPK\"#" "$VOICE_CFG"
echo "  voice.yaml updated (old copy: $backup):"
sudo grep -E '^  (capture|playback)_device:' "$VOICE_CFG" | sed 's/^/  /'

echo
echo "To try them with the robot (nothing here moves: spider-body stays off):"
echo "  sudo systemctl start spider-camera spider-voice"
echo "  journalctl -fu spider-voice"
