#!/usr/bin/env python3
"""Compare nv12 vs nv21 decode of one raw AtomISP frame."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
# Keep stream running — grab one frame from the live v4l pipe is hard.
# Instead stop stream briefly, grab 2 frames, restart.
systemctl stop ha-kiosk-camera-stream.service
sleep 1
pkill -9 -f 'v4l2-ctl --stream' || true
/opt/ha-kiosk/scripts/load-atomisp.sh || true
# Capture one Size Image buffer
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw
ls -l /tmp/cam.raw
# Decode as nv12 and nv21
ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 -i /tmp/cam.raw \
  -vf crop=1584:1184:0:0,scale=960:720 -frames:v 1 /tmp/dec_nv12.jpg
ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv21 -video_size 1600x1184 -i /tmp/cam.raw \
  -vf crop=1584:1184:0:0,scale=960:720 -frames:v 1 /tmp/dec_nv21.jpg
# Also try yuv420p interpretation of same bytes
ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt yuv420p -video_size 1600x1184 -i /tmp/cam.raw \
  -vf crop=1584:1184:0:0,scale=960:720 -frames:v 1 /tmp/dec_yuv420p.jpg
python3 - <<'PY'
from PIL import Image, ImageStat
for n in ('dec_nv12','dec_nv21','dec_yuv420p'):
  im=Image.open(f'/tmp/{n}.jpg').convert('RGB')
  st=ImageStat.Stat(im)
  print(n, im.size, [round(x,1) for x in st.mean])
PY
systemctl start ha-kiosk-camera-stream.service
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/cmp_nv.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/cmp_nv.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/cmp_nv.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    sftp = c.open_sftp()
    for name in ("dec_nv12.jpg", "dec_nv21.jpg", "dec_yuv420p.jpg"):
        try:
            blob = sftp.file(f"/tmp/{name}", "rb").read()
            (OUT / name).write_bytes(blob)
            print("saved", name, len(blob))
        except Exception as e:
            print("miss", name, e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
