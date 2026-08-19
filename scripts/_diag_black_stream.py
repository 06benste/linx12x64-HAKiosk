#!/usr/bin/env python3
"""Diagnose black camera stream frames."""
from __future__ import annotations

import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

REMOTE = r"""
set -uo pipefail
echo '=== services ==='
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service || true
cat /opt/ha-kiosk/config/camera_power 2>/dev/null || true
echo '=== processes ==='
ps -eo pid,cmd | awk '/camera-stream-server|v4l2-ctl --stream|ffmpeg.*mjpeg/ {print}' || true
echo '=== video device ==='
ls -la /dev/video0 2>&1 || true
v4l2-ctl -d /dev/video0 --all 2>&1 | head -60 || true
echo '=== health ==='
curl -fsS --max-time 5 http://127.0.0.1:17824/health || echo health_fail
echo
echo '=== snapshots ==='
curl -fsS --max-time 45 -o /tmp/snap_graded.jpg http://127.0.0.1:17824/snapshot.jpg || echo graded_fail
curl -fsS --max-time 45 -o /tmp/snap_plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1' || echo plain_fail
ls -la /tmp/snap_graded.jpg /tmp/snap_plain.jpg 2>&1 || true
python3 - <<'PY'
from PIL import Image
import statistics
for name in ('/tmp/snap_graded.jpg','/tmp/snap_plain.jpg'):
    try:
        im = Image.open(name).convert('RGB')
        px = list(im.getdata())
        # sample every 50th pixel
        sample = px[::50]
        means = [sum(p)/3 for p in sample]
        print(name, 'size', im.size, 'mean_luma', round(statistics.mean(means),1),
              'min', round(min(means),1), 'max', round(max(means),1),
              'bytes', __import__('os').path.getsize(name))
    except Exception as e:
        print(name, 'ERR', e)
PY
echo '=== journal ==='
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/diag-cam-black.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/diag-cam-black.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/diag-cam-black.sh",
        timeout=120,
        get_pty=True,
    )
    print(o.read().decode("utf-8", "replace"))
    # pull snaps
    sftp = c.open_sftp()
    for name in ("snap_graded.jpg", "snap_plain.jpg"):
        try:
            sftp.get(f"/tmp/{name}", f"C:/Users/ben_s/Projects/linx-ha-kiosk/logs/{name}")
            print("downloaded", name)
        except Exception as e:
            print("download fail", name, e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
