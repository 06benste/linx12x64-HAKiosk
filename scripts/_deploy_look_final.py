#!/usr/bin/env python3
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
install -m 644 /tmp/ha-lookf/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 644 /tmp/ha-lookf/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
install -m 755 /tmp/ha-lookf/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 755 /tmp/ha-lookf/snap_stats.py /tmp/snap_stats.py
systemctl restart ha-kiosk-camera-stream.service
# mqtt keeps a stream client open
systemctl try-restart ha-kiosk-mqtt.service || true
for i in $(seq 1 30); do
  if curl -fsS --max-time 3 -o /dev/null http://127.0.0.1:17824/snapshot.jpg; then break; fi
  sleep 1
done
python3 /tmp/snap_stats.py
journalctl -u ha-kiosk-camera-stream -n 8 --no-pager
ps aux | grep 'ffmpeg.*rawvideo' | grep -v grep || true
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    shutil.copyfile(ROOT / "scripts" / "camera_preview.py", ROOT / "tools" / "camera_preview.py")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-lookf")
    except OSError:
        pass
    for name, src in (
        ("camera_preview.json", ROOT / "config" / "camera_preview.json"),
        ("camera_preview.py", ROOT / "scripts" / "camera_preview.py"),
        ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
        ("snap_stats.py", ROOT / "scripts" / "_remote_snap_stats.py"),
    ):
        with sftp.file(f"/tmp/ha-lookf/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/deploy-lookf.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-lookf.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-lookf.sh", timeout=200, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    for name, remote in (("graded.jpg", "/tmp/ha_user_graded.jpg"), ("plain.jpg", "/tmp/ha_user_plain.jpg")):
        blob = sftp.file(remote, "rb").read()
        (OUT / name).write_bytes(blob)
        print("saved", name, len(blob), flush=True)
    sftp.close()
    c.close()
    if code != 0:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
