#!/usr/bin/env python3
"""Fix systemd dep cycle and start MQTT + camera stream."""
from __future__ import annotations

import pathlib
import sys
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-fix/ha-kiosk-mqtt.service /etc/systemd/system/ha-kiosk-mqtt.service
install -m 644 /tmp/ha-fix/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service
systemctl daemon-reload
systemctl enable ha-kiosk-mqtt.service ha-kiosk-camera-stream.service
systemctl reset-failed ha-kiosk-mqtt.service ha-kiosk-camera-stream.service || true
systemctl restart ha-kiosk-camera-stream.service
sleep 2
systemctl restart ha-kiosk-mqtt.service
sleep 4
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service
systemd-analyze verify ha-kiosk-mqtt.service ha-kiosk-camera-stream.service 2>&1 || true
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
echo
journalctl -u ha-kiosk-mqtt.service -n 8 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-fix")
    except OSError:
        pass
    for name in ("ha-kiosk-mqtt.service", "ha-kiosk-camera-stream.service"):
        with sftp.file(f"/tmp/ha-fix/{name}", "wb") as f:
            f.write((ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/ha-fix.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/ha-fix.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/ha-fix.sh", timeout=60, get_pty=True)
    print(o.read().decode("utf-8", errors="replace"))
    c.close()
    time.sleep(1)
    try:
        print("stream", urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=5).read().decode())
    except Exception as e:
        print("stream", e)
    try:
        print("power", urllib.request.urlopen(f"http://{HOST}:17823/health", timeout=3).read().decode())
    except Exception as e:
        print("power", e)


if __name__ == "__main__":
    main()
