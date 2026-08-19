#!/usr/bin/env python3
"""Revert MQTT camera experiment and clear retained discovery/state topics."""
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
install -m 755 /tmp/ha-cam-revert/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
chown kioskuser:kioskuser /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py

# Restore mqtt unit without camera-only X11 env (keep User=kioskuser — mqtt.env is owned by them)
UNIT=/etc/systemd/system/ha-kiosk-mqtt.service
cat > "$UNIT" <<'EOF'
[Unit]
Description=HA kiosk MQTT device bridge
After=network-online.target ha-kiosk-power.service
Wants=network-online.target
Requires=ha-kiosk-power.service

[Service]
Type=simple
User=kioskuser
ExecStart=/usr/bin/python3 /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
Restart=always
RestartSec=5
EnvironmentFile=-/opt/ha-kiosk/mqtt.env

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl restart ha-kiosk-mqtt.service
sleep 3
journalctl -u ha-kiosk-mqtt.service -n 10 --no-pager
echo OK
"""


def clear_camera_mqtt() -> None:
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        print("paho not available; skip MQTT clear")
        return

    try:
        cli = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    except Exception:
        cli = mqtt.Client()
    cli.username_pw_set("kioskuser", "kiosk")
    cli.connect("192.168.8.110", 1883, 60)
    topics = [
        "homeassistant/camera/hakiosk_tablet/camera/config",
        "homeassistant/sensor/hakiosk_tablet/camera_source/config",
        "homeassistant/button/hakiosk_tablet/camera_snapshot/config",
        "hakiosk/hakiosk_tablet/camera",
        "hakiosk/hakiosk_tablet/camera_source",
    ]
    for t in topics:
        cli.publish(t, b"", qos=1, retain=True)
        print("cleared", t)
    cli.disconnect()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    clear_camera_mqtt()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-cam-revert")
    except OSError:
        pass
    local = ROOT / "scripts" / "ha-kiosk-mqtt.py"
    with sftp.file("/tmp/ha-cam-revert/ha-kiosk-mqtt.py", "wb") as f:
        f.write(local.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/revert-cam.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/revert-cam.sh", 0o755)
    sftp.close()
    _, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/revert-cam.sh", timeout=60
    )
    print(stdout.read().decode())
    err = stderr.read().decode()
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1200:])
    code = stdout.channel.recv_exit_status()
    client.close()
    if code != 0:
        raise SystemExit(code)
    time.sleep(1)
    clear_camera_mqtt()
    print("camera reverted")


if __name__ == "__main__":
    main()
