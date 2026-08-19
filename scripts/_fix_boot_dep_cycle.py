#!/usr/bin/env python3
"""Fix atomisp unit ordering cycle and start mqtt + camera-stream."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-fix-units/ha-kiosk-atomisp.service /etc/systemd/system/ha-kiosk-atomisp.service
install -m 644 /tmp/ha-fix-units/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service
install -m 644 /tmp/ha-fix-units/ha-kiosk-mqtt.service /etc/systemd/system/ha-kiosk-mqtt.service
systemctl daemon-reload
systemctl enable ha-kiosk-atomisp.service ha-kiosk-camera-stream.service ha-kiosk-mqtt.service
# Verify no cycle in the transaction
systemd-analyze verify ha-kiosk-atomisp.service ha-kiosk-mqtt.service ha-kiosk-camera-stream.service 2>&1 || true
systemctl start ha-kiosk-atomisp.service
systemctl restart ha-kiosk-mqtt.service
systemctl restart ha-kiosk-camera-stream.service
sleep 3
systemctl is-enabled ha-kiosk-mqtt.service ha-kiosk-camera-stream.service ha-kiosk-atomisp.service
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service ha-kiosk-atomisp.service ha-kiosk-power.service
journalctl -u ha-kiosk-mqtt.service -n 15 --no-pager
journalctl -u ha-kiosk-camera-stream.service -n 10 --no-pager
# Show fixed atomisp unit
systemctl cat ha-kiosk-atomisp.service
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-fix-units")
    except OSError:
        pass
    for name in (
        "ha-kiosk-atomisp.service",
        "ha-kiosk-camera-stream.service",
        "ha-kiosk-mqtt.service",
    ):
        data = (ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(f"/tmp/ha-fix-units/{name}", "wb") as f:
            f.write(data)
        print("uploaded", name, flush=True)
    with sftp.file("/tmp/fix-units.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-units.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/fix-units.sh", timeout=90, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    if o.channel.recv_exit_status() != 0:
        raise SystemExit(1)
    c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
