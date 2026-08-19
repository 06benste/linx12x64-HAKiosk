#!/usr/bin/env bash
# Install power drawer (extension files + localhost power API).
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_ROOT=/opt/ha-kiosk
KIOSK_USER="${KIOSK_USER:-kioskuser}"
EXT_SRC="$REPO_ROOT/chromium-extension"
EXT_DST="$INSTALL_ROOT/chromium-extension"

# python3-paho-mqtt is for the MQTT/HA device bridge (ha-kiosk-mqtt.py) —
# installed here so it's on disk whenever the setup screen's MQTT tab wants
# to enable it, without needing a separate manual step first. ffmpeg + grim
# are ha-kiosk-mqtt.py's dashboard-screenshot feature (grim for the default
# cage/Wayland kiosk, ffmpeg as the X11 fallback and to convert grim's PNG
# to JPEG either way). i2c-tools is power-api.py's charge-LED control
# (direct AXP288 register access — see set_chgled). All installed here
# rather than only via 09-install-camera.sh so these keep working under
# SKIP_CAMERA=1.
#
# firmware-intel-sound + alsa-ucm-conf: this board's chtnau8824 audio codec
# ships with neither its Intel SST DSP firmware (intel/fw_sst_22a8.bin) nor
# an ALSA UCM profile present by default, so without these two packages
# `aplay`/anything else fails at hw_params with "no backend DAIs enabled for
# Audio Port" (missing firmware) or an outright device-open error (missing
# UCM) — confirmed live. Installed here as a real prerequisite fix even
# though nothing in this project plays audio today (no volume control is
# exposed in the UI — every speaker-DAC volume/route was confirmed correctly
# unmuted end-to-end via `alsaucm -c chtnau8824 set _verb HiFi set _enadev
# Speaker`, yet no audible sound was ever produced, pointing to a likely
# undocumented speaker-amp enable GPIO on this specific board that's a
# separate, unsolved problem from the software audio stack these two
# packages fix).
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends xinput alsa-utils python3-paho-mqtt ffmpeg grim i2c-tools firmware-intel-sound alsa-ucm-conf

# power-api.py's charge-LED control needs /dev/i2c-* — load on demand, same
# as camera-stream-server.py already does for its own i2c exposure control.
modprobe i2c-dev || true

mkdir -p "$INSTALL_ROOT/scripts/static" "$EXT_DST"
install -m 755 "$SCRIPT_DIR/power-api.py" "$INSTALL_ROOT/scripts/power-api.py"
install -m 644 "$SCRIPT_DIR/ha-kiosk-power.service" /etc/systemd/system/ha-kiosk-power.service

# Wake-on-touch: backlight-based blanking (bl_power) has no built-in
# "any input wakes the panel" behavior the way X11 DPMS did — this watches
# /dev/input/event* and undoes an intentional blank on any activity.
install -m 755 "$SCRIPT_DIR/wake-on-touch.py" "$INSTALL_ROOT/scripts/wake-on-touch.py"
install -m 644 "$SCRIPT_DIR/ha-kiosk-wake-on-touch.service" /etc/systemd/system/ha-kiosk-wake-on-touch.service

install -m 755 "$SCRIPT_DIR/setup-wizard.py" "$INSTALL_ROOT/scripts/setup-wizard.py"
install -m 644 "$SCRIPT_DIR/static/setup.html" "$INSTALL_ROOT/scripts/static/setup.html"
install -m 644 "$SCRIPT_DIR/ha-kiosk-setup.service" /etc/systemd/system/ha-kiosk-setup.service

# MQTT/HA device bridge — files installed but the service is left disabled
# until the user enters broker credentials via the setup screen's MQTT tab
# (POST /api/save-mqtt enables it).
install -m 755 "$SCRIPT_DIR/ha-kiosk-mqtt.py" "$INSTALL_ROOT/scripts/ha-kiosk-mqtt.py"
install -m 644 "$SCRIPT_DIR/ha-kiosk-mqtt.service" /etc/systemd/system/ha-kiosk-mqtt.service
if [[ ! -f "$INSTALL_ROOT/mqtt.env" ]]; then
  if [[ -f "$REPO_ROOT/mqtt.env.example" ]]; then
    install -m 600 "$REPO_ROOT/mqtt.env.example" "$INSTALL_ROOT/mqtt.env"
  else
    cat >"$INSTALL_ROOT/mqtt.env" <<'EOF'
MQTT_HOST=192.168.8.110
MQTT_PORT=1883
MQTT_USER=
MQTT_PASSWORD=
MQTT_INTERVAL=15
EOF
    chmod 600 "$INSTALL_ROOT/mqtt.env"
  fi
fi

# LAN auth token: power-api.py (17823) and camera-stream-server.py (17824)
# both bind 0.0.0.0 (Home Assistant needs to reach them across the network
# for the REST fallback package and the live mjpeg camera respectively) — so
# unlike setup-wizard.py, which has no legitimate cross-machine caller and is
# bound to loopback-only, these two need a real credential instead. Requests
# from the tablet itself (drawer, ha-kiosk-mqtt.py) are always exempted by
# _client_is_local()/authorized(), so nothing on-device needs this value —
# only a remote Home Assistant config that calls these APIs does.
if [[ ! -f "$INSTALL_ROOT/api.token" ]]; then
  python3 - <<'PY'
import secrets, pathlib
p = pathlib.Path("/opt/ha-kiosk/api.token")
p.write_text(secrets.token_hex(16))
p.chmod(0o600)
print("api.token created:", p.read_text())
PY
fi

# Sync extension (preserve generated config.js if present)
if [[ -f "$EXT_DST/config.js" && ! -f "$EXT_SRC/config.js" ]]; then
  cp -a "$EXT_DST/config.js" /tmp/ha-kiosk-config.js.bak
fi
cp -a "$EXT_SRC/." "$EXT_DST/"
if [[ -f /tmp/ha-kiosk-config.js.bak ]]; then
  mv /tmp/ha-kiosk-config.js.bak "$EXT_DST/config.js"
fi
# Ensure config exists
if [[ ! -f "$EXT_DST/config.js" ]]; then
  cat >"$EXT_DST/config.js" <<'EOF'
window.HA_KIOSK_AUTH = { user: "kioskuser", pass: "kiosk1" };
EOF
fi

chown -R "$KIOSK_USER:$KIOSK_USER" "$INSTALL_ROOT" 2>/dev/null || true

systemctl daemon-reload
systemctl enable --now ha-kiosk-power.service
systemctl enable --now ha-kiosk-setup.service
systemctl enable --now ha-kiosk-wake-on-touch.service

echo "Power drawer installed."
echo "Restart the kiosk session to reload the extension, e.g.:"
echo "  systemctl restart getty@tty1.service"
echo
echo "LAN API token (needed for Home Assistant's REST sensors / live mjpeg"
echo "camera to reach this tablet across the network — not needed on-device):"
echo "  $(cat "$INSTALL_ROOT/api.token")"
