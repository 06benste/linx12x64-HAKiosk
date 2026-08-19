#!/usr/bin/env python3
"""Probe V4L fmt and try crop x-offsets to fix horizontal wrap."""
import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
OUT.mkdir(exist_ok=True)

SCRIPT = r"""
set -e
systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo' || true
sleep 1
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
sleep 1
echo === FMT ===
v4l2-ctl -d /dev/video0 --set-input=0 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --get-fmt-video
rm -f /tmp/one.nv12
timeout -s KILL 12 v4l2-ctl -d /dev/video0 --set-input=0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=3 --stream-count=4 --stream-to=/tmp/one.nv12 || true
ls -l /tmp/one.nv12
python3 - <<'PY'
from pathlib import Path
n = Path('/tmp/one.nv12').stat().st_size
print('bytes', n)
print('frames_2842624', n / 2842624)
print('frames_2841600', n / 2841600)
# keep last full padded frame
FS=2842624
raw=Path('/tmp/one.nv12').read_bytes()
if len(raw) >= FS:
    Path('/tmp/frame.nv12').write_bytes(raw[-FS:][:2841600])
    print('wrote frame.nv12', 2841600)
PY
for x in 0 8 16 24 32 48 64 80 96 112 128 144 160; do
  ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 \
    -i /tmp/frame.nv12 -vf "crop=1584:1184:${x}:0,scale=800:600" -frames:v 1 "/tmp/crop_x${x}.jpg" || true
  ls -l "/tmp/crop_x${x}.jpg" 2>/dev/null || true
done
# also try crop width 1600 (no crop) and 1568
ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 \
  -i /tmp/frame.nv12 -vf 'scale=800:600' -frames:v 1 /tmp/crop_full1600.jpg || true
systemctl start ha-kiosk-camera-stream.service || true
"""


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_crop_probe.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/_crop_probe.sh", 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(120)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_crop_probe.sh")
    buf = b""
    deadline = time.time() + 120
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    print(buf.decode("utf-8", "replace")[-4000:])
    sftp = c.open_sftp()
    for x in [0, 8, 16, 32, 64, 80, 96, 128, 160]:
        src = f"/tmp/crop_x{x}.jpg"
        try:
            (OUT / f"crop_x{x}.jpg").write_bytes(sftp.file(src, "rb").read())
            print("saved", src)
        except Exception as e:
            print("miss", src, e)
    try:
        (OUT / "crop_full1600.jpg").write_bytes(sftp.file("/tmp/crop_full1600.jpg", "rb").read())
    except Exception:
        pass
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
