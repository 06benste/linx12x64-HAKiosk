#!/bin/bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends openbox xdotool

cat > /opt/ha-kiosk/scripts/kiosk-x11.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
INSTALL_ROOT=/opt/ha-kiosk
URL="$(cat "$INSTALL_ROOT/url" 2>/dev/null || true)"
[[ -n "$URL" ]] || URL='http://192.168.8.110:8123/dashboard-kiosk?kiosk'
PROFILE_DIR=$INSTALL_ROOT/chromium-profile
EXT_DIR=$INSTALL_ROOT/chromium-extension
mkdir -p "$PROFILE_DIR"

# Let Wi-Fi / DHCP settle after boot, then wait briefly for HA
sleep 5
python3 - "$URL" <<'PY' || true
import sys, time, urllib.request
url = sys.argv[1]
deadline = time.time() + 45
while time.time() < deadline:
    try:
        urllib.request.urlopen(url, timeout=2)
        break
    except Exception:
        time.sleep(1)
PY

# Detect panel size
W=1920
H=1080
if command -v xrandr >/dev/null; then
  geom=$(xrandr --current | awk '/ connected primary/{print $4; exit}')
  if [[ "$geom" =~ ^([0-9]+)x([0-9]+) ]]; then
    W="${BASH_REMATCH[1]}"
    H="${BASH_REMATCH[2]}"
  fi
fi

command -v unclutter >/dev/null && unclutter -idle 0.5 -root &

# After Chromium starts, force true fullscreen geometry
(
  for i in $(seq 1 30); do
    sleep 1
    wid=$(xdotool search --onlyvisible --class chromium 2>/dev/null | head -n1 || true)
    if [[ -n "$wid" ]]; then
      xdotool windowmove "$wid" 0 0
      xdotool windowsize "$wid" "$W" "$H"
      xdotool windowactivate "$wid"
      break
    fi
  done
) &

CHROME=/usr/lib/chromium/chromium
[[ -x "$CHROME" ]] || CHROME="$(command -v chromium)"
EXTRA=()
if [[ -f "$EXT_DIR/manifest.json" ]]; then
  EXTRA+=(--disable-extensions-except="$EXT_DIR" --load-extension="$EXT_DIR")
else
  EXTRA+=(--disable-extensions)
fi
exec "$CHROME" \
  --user-data-dir="$PROFILE_DIR" \
  --ozone-platform=x11 \
  --kiosk --start-fullscreen --start-maximized \
  --window-size="${W},${H}" \
  --window-position=0,0 \
  --force-device-scale-factor=1 \
  --no-first-run --noerrdialogs --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-translate --disable-sync \
  --disable-features=TranslateUI,AudioServiceOutOfProcess,UseChromeOSDirectVideoDecoder \
  --check-for-update-interval=31536000 \
  --password-store=basic \
  --autoplay-policy=no-user-gesture-required \
  --disk-cache-size=33554432 \
  --disable-pinch \
  --disable-gpu --disable-gpu-compositing --disable-gpu-rasterization \
  --disable-accelerated-2d-canvas --disable-accelerated-video-decode \
  --disable-software-rasterizer --use-gl=swiftshader \
  --disable-dev-shm-usage \
  "${EXTRA[@]}" \
  "$URL"
EOF
chmod 755 /opt/ha-kiosk/scripts/kiosk-x11.sh

cat > /home/kioskuser/.xinitrc << 'EOF'
#!/bin/sh
xset s off
/opt/ha-kiosk/scripts/keep-awake-x11.sh &
openbox &
sleep 0.5
exec /opt/ha-kiosk/scripts/kiosk-x11.sh
EOF
chmod 755 /home/kioskuser/.xinitrc
chown kioskuser:kioskuser /home/kioskuser/.xinitrc
chown -R kioskuser:kioskuser /opt/ha-kiosk

systemctl restart getty@tty1.service
echo FIX_OK
