#!/usr/bin/env python3
"""Deploy MQTT camera try: install ffmpeg, update bridge, restart mqtt service."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
# ffmpeg for V4L2 / x11grab snapshots
if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq ffmpeg
fi
install -m 755 /tmp/ha-cam/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
chown kioskuser:kioskuser /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py

# Ensure mqtt service can see the kiosk X session for screen fallback
UNIT=/etc/systemd/system/ha-kiosk-mqtt.service
if [[ -f "$UNIT" ]]; then
  if ! grep -q '^Environment=DISPLAY=' "$UNIT"; then
    # insert after [Service]
    sed -i '/^\[Service\]/a Environment=DISPLAY=:0\nEnvironment=XAUTHORITY=/home/kioskuser/.Xauthority' "$UNIT"
  fi
  # Prefer running as kioskuser if currently root (Xauth ownership)
  if grep -q '^User=' "$UNIT"; then
    sed -i 's/^User=.*/User=kioskuser/' "$UNIT"
  else
    sed -i '/^\[Service\]/a User=kioskuser' "$UNIT"
  fi
  systemctl daemon-reload
fi

systemctl restart ha-kiosk-mqtt.service
sleep 4
journalctl -u ha-kiosk-mqtt.service -n 25 --no-pager
# Quick local capture smoke test as kioskuser
sudo -u kioskuser env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority \
  ffmpeg -hide_banner -loglevel error -f x11grab -video_size 1280x800 -i :0.0 \
  -frames:v 1 -q:v 8 -f mjpeg /tmp/cam-try.jpg 2>&1 || true
ls -la /tmp/cam-try.jpg 2>/dev/null || true
file /tmp/cam-try.jpg 2>/dev/null || true
echo OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-cam")
    except OSError:
        pass
    local = ROOT / "scripts" / "ha-kiosk-mqtt.py"
    with sftp.file("/tmp/ha-cam/ha-kiosk-mqtt.py", "wb") as f:
        f.write(local.read_bytes().replace(b"\r\n", b"\n"))
    print("uploaded ha-kiosk-mqtt.py", flush=True)
    with sftp.file("/tmp/deploy-cam.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-cam.sh", 0o755)
    sftp.close()
    _, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-cam.sh", timeout=300
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    filtered = "\n".join(l for l in err.splitlines() if "password" not in l.lower())
    print("STDERR:", filtered[-2500:])
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise SystemExit(code)

    time.sleep(2)
    try:
        import paho.mqtt.client as mqtt

        seen: list[tuple[str, int | str]] = []

        def on_message(c, u, msg):
            if msg.topic.endswith("/camera"):
                seen.append((msg.topic, len(msg.payload)))
            else:
                seen.append((msg.topic, msg.payload.decode(errors="replace")[:80]))

        try:
            cli = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        except Exception:
            cli = mqtt.Client()
        cli.username_pw_set("kioskuser", "kiosk")
        cli.on_message = on_message
        cli.connect("192.168.8.110", 1883, 60)
        cli.subscribe("homeassistant/camera/hakiosk_tablet/#")
        cli.subscribe("hakiosk/hakiosk_tablet/camera")
        cli.subscribe("hakiosk/hakiosk_tablet/camera_source")
        cli.loop_start()
        time.sleep(5)
        cli.loop_stop()
        cli.disconnect()
        print("mqtt samples:")
        for t, p in seen:
            print(" ", t, "=", p)
    except Exception as exc:
        print("mqtt check skipped:", exc)
    client.close()


if __name__ == "__main__":
    main()
