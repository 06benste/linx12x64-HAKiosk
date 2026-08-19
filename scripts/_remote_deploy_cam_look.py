#!/usr/bin/env python3
"""Deploy approved camera preview config + capture script to the tablet."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
if ! python3 -c 'from PIL import Image' 2>/dev/null; then
  apt-get update -qq
  apt-get install -y -qq python3-pil
fi
install -d -m 755 /opt/ha-kiosk/config /opt/ha-kiosk/scripts
install -m 644 /tmp/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 755 /tmp/capture-tablet-cam.sh /opt/ha-kiosk/scripts/capture-tablet-cam.sh
install -m 755 /tmp/capture-tablet-cam.py /opt/ha-kiosk/scripts/capture-tablet-cam.py
/opt/ha-kiosk/scripts/capture-tablet-cam.sh /tmp/ha-kiosk-camera.jpg
ls -la /tmp/ha-kiosk-camera.jpg
file /tmp/ha-kiosk-camera.jpg
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    sftp.put(str(ROOT / "config" / "camera_preview.json"), "/tmp/camera_preview.json")
    with sftp.file("/tmp/capture-tablet-cam.sh", "w") as f:
        f.write((ROOT / "scripts" / "capture-tablet-cam.sh").read_text(encoding="utf-8").replace("\r\n", "\n"))
    sftp.chmod("/tmp/capture-tablet-cam.sh", 0o755)
    with sftp.file("/tmp/capture-tablet-cam.py", "w") as f:
        f.write((ROOT / "scripts" / "capture-tablet-cam.py").read_text(encoding="utf-8").replace("\r\n", "\n"))
    sftp.chmod("/tmp/capture-tablet-cam.py", 0o755)
    with sftp.file("/tmp/deploy_cam_look.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy_cam_look.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy_cam_look.sh",
        timeout=120,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    rc = stdout.channel.recv_exit_status()

    # pull sample
    sftp = c.open_sftp()
    out = ROOT / "logs" / "cam_approved_look.jpg"
    try:
        sftp.get("/tmp/ha-kiosk-camera.jpg", str(out))
        print(f"downloaded {out}", flush=True)
    except Exception as e:
        print("download failed", e, flush=True)
    sftp.close()
    c.close()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
