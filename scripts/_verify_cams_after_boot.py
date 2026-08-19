#!/usr/bin/env python3
"""Verify front+rear cameras after power cycle with CSI port fix."""
from __future__ import annotations

import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

CMD = r"""
set -euxo pipefail
echo '=== uptime ==='
uptime
echo '=== dmesg cams ==='
dmesg | grep -iE 'LINX_CSI|gc2235|detected .*camera|already has|camera pdata|sensor ID' | tail -n 50
echo '=== media ==='
media-ctl -p -d /dev/media0 2>&1 | head -n 110
echo '=== stop stream for input test ==='
systemctl stop ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 0.5
echo '=== inputs ==='
v4l2-ctl -d /dev/video0 --list-inputs 2>&1 || true
echo '=== front ==='
rm -f /tmp/cam_front.raw /tmp/cam_front.jpg /tmp/cam_rear.raw /tmp/cam_rear.jpg
timeout -s KILL 12 v4l2-ctl -d /dev/video0 --set-input=0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=3 --stream-count=8 --stream-to=/tmp/cam_front.raw 2>&1 | tail -n 20 || true
ls -la /tmp/cam_front.raw 2>/dev/null || true
if [[ -s /tmp/cam_front.raw ]]; then
  ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 \
    -i /tmp/cam_front.raw -vf 'crop=1584:1184:0:0,scale=640:480' -frames:v 1 /tmp/cam_front.jpg || true
fi
echo '=== rear ==='
if v4l2-ctl -d /dev/video0 --list-inputs 2>&1 | grep -q 'Input       : 1'; then
  timeout -s KILL 15 v4l2-ctl -d /dev/video0 --set-input=1 \
    --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
    --stream-mmap=3 --stream-count=10 --stream-to=/tmp/cam_rear.raw 2>&1 | tail -n 30 || true
  ls -la /tmp/cam_rear.raw 2>/dev/null || true
  if [[ -s /tmp/cam_rear.raw ]]; then
    ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 \
      -i /tmp/cam_rear.raw -vf 'crop=1584:1184:0:0,scale=640:480' -frames:v 1 /tmp/cam_rear.jpg || true
    ls -la /tmp/cam_rear.jpg 2>/dev/null || true
  fi
else
  echo NO_INPUT_1
fi
# restore front stream service (input 0)
v4l2-ctl -d /dev/video0 --set-input=0 2>/dev/null || true
systemctl start ha-kiosk-camera-stream.service || true
sleep 4
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
echo
echo VERIFY_DONE
"""


def main() -> None:
    for attempt in range(18):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username="kioskuser", password=PASS, timeout=12, allow_agent=False, look_for_keys=False)
            print("connected attempt", attempt)
            break
        except Exception as e:
            print("wait", attempt, type(e).__name__, e)
            time.sleep(5)
    else:
        raise SystemExit("unreachable")

    sftp = c.open_sftp()
    with sftp.file("/tmp/verify_cams.sh", "w") as f:
        f.write(CMD)
    sftp.chmod("/tmp/verify_cams.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/verify_cams.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    sftp = c.open_sftp()
    for src, dst in (("/tmp/cam_front.jpg", "front_after_boot.jpg"), ("/tmp/cam_rear.jpg", "rear.jpg")):
        try:
            blob = sftp.file(src, "rb").read()
            (OUT / dst).write_bytes(blob)
            print("saved", dst, len(blob))
        except Exception as e:
            print("missing", src, e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
