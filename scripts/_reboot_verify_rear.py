#!/usr/bin/env python3
"""Reboot tablet and verify front+rear after CSI port fix."""
from __future__ import annotations

import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
print("rebooting...")
c.exec_command(f"echo {PASS} | sudo -S -p '' reboot", timeout=10)
time.sleep(5)
c.close()

# wait for ssh
for i in range(40):
    time.sleep(5)
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username="kioskuser", password=PASS, timeout=8, allow_agent=False, look_for_keys=False)
        _, o, _ = c.exec_command("uptime", timeout=10)
        up = o.read().decode()
        print("up", up.strip())
        if "min" in up or "sec" in up or "user" in up:
            break
        c.close()
    except Exception as e:
        print("wait", i, type(e).__name__)
else:
    raise SystemExit("tablet did not come back")

CMD = r"""
set -euxo pipefail
sleep 8
dmesg | grep -iE 'LINX_CSI|gc2235|detected .*camera|already has|camera pdata|sensor ID' | tail -n 40
echo '=== media ==='
media-ctl -p -d /dev/media0 2>&1 | head -n 100
echo '=== inputs ==='
# stop stream for clean query
systemctl stop ha-kiosk-camera-stream.service || true
sleep 1
v4l2-ctl -d /dev/video0 --list-inputs 2>&1 || true
echo '=== front capture ==='
timeout -s KILL 10 v4l2-ctl -d /dev/video0 --set-input=0 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --stream-mmap=3 --stream-count=6 --stream-to=/tmp/cam_front.raw 2>&1 | tail -n 15 || true
ls -la /tmp/cam_front.raw 2>/dev/null || true
echo '=== rear capture ==='
if v4l2-ctl -d /dev/video0 --list-inputs 2>&1 | grep -q 'Input       : 1'; then
  timeout -s KILL 12 v4l2-ctl -d /dev/video0 --set-input=1 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --stream-mmap=3 --stream-count=8 --stream-to=/tmp/cam_rear.raw 2>&1 | tail -n 30 || true
  ls -la /tmp/cam_rear.raw 2>/dev/null || true
  if [[ -s /tmp/cam_rear.raw ]]; then
    ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 -i /tmp/cam_rear.raw \
      -vf 'crop=1584:1184:0:0,scale=800:600' -frames:v 1 /tmp/cam_rear.jpg || true
    ls -la /tmp/cam_rear.jpg 2>/dev/null || true
  fi
else
  echo NO_INPUT_1
fi
systemctl start ha-kiosk-camera-stream.service || true
"""
sftp = c.open_sftp()
with sftp.file("/tmp/verify_rear_boot.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/verify_rear_boot.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/verify_rear_boot.sh", timeout=180, get_pty=True)
print(o.read().decode("utf-8", "replace"))
sftp = c.open_sftp()
try:
    blob = sftp.file("/tmp/cam_rear.jpg", "rb").read()
    (OUT / "rear.jpg").write_bytes(blob)
    print("saved rear.jpg", len(blob))
except Exception as e:
    print("no rear jpg", e)
sftp.close()
c.close()
