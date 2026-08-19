#!/usr/bin/env python3
"""Deploy stronger look + centre-weighted AE; pull snaps."""
from __future__ import annotations

import pathlib
import shutil
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-look3/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 644 /tmp/ha-look3/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 25); do
  if curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:17824/snapshot.jpg; then break; fi
  sleep 1
done
python3 /tmp/snap_stats.py
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    shutil.copyfile(ROOT / "scripts" / "camera_preview.py", ROOT / "tools" / "camera_preview.py")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-look3")
    except OSError:
        pass
    for name, src in (
        ("camera_preview.json", ROOT / "config" / "camera_preview.json"),
        ("camera_preview.py", ROOT / "scripts" / "camera_preview.py"),
    ):
        with sftp.file(f"/tmp/ha-look3/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/snap_stats.py", "wb") as f:
        f.write((ROOT / "scripts" / "_remote_snap_stats.py").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/deploy-look3.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-look3.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-look3.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    for name, remote in (("graded.jpg", "/tmp/ha_graded.jpg"), ("plain.jpg", "/tmp/ha_plain.jpg")):
        blob = sftp.file(remote, "rb").read()
        (OUT / name).write_bytes(blob)
        print("saved", name, len(blob), flush=True)
    sftp.close()
    c.close()
    if code != 0:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
