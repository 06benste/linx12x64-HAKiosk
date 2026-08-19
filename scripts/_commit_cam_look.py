#!/usr/bin/env python3
"""Push camera_preview.json to the tablet and restart the stream service."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -d -m 755 /opt/ha-kiosk/config /opt/ha-kiosk/scripts
install -m 644 /tmp/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
if [[ -f /tmp/camera_preview.py ]]; then
  install -m 644 /tmp/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
fi
systemctl restart ha-kiosk-camera-stream.service
sleep 2
systemctl is-active ha-kiosk-camera-stream.service
python3 - <<'PY'
import json
print(json.load(open("/opt/ha-kiosk/config/camera_preview.json")))
PY
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = ROOT / "config" / "camera_preview.json"
    print(f"committing {cfg}", flush=True)
    print(cfg.read_text(encoding="utf-8"), flush=True)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    data = cfg.read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/camera_preview.json", "wb") as f:
        f.write(data)
    preview_py = ROOT / "scripts" / "camera_preview.py"
    if preview_py.exists():
        with sftp.file("/tmp/camera_preview.py", "wb") as f:
            f.write(preview_py.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/commit_cam_look.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/commit_cam_look.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/commit_cam_look.sh",
        timeout=60,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    rc = stdout.channel.recv_exit_status()
    c.close()
    if rc != 0:
        raise SystemExit(rc)
    print("OK — look committed to tablet + stream restarted", flush=True)


if __name__ == "__main__":
    main()
