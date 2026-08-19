#!/usr/bin/env python3
"""Hotfix white-clip grade mapping and verify a snapshot is not blown out."""
from __future__ import annotations

import pathlib
import sys

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
install -m 755 /tmp/ha-whitefix/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-whitefix/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 20); do
  if curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:17824/health; then break; fi
  sleep 1
done
python3 - <<'PY'
import json, time, urllib.request, threading
from PIL import Image, ImageStat
import io

def suck():
    try:
        urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(256)
    except Exception:
        pass
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
data = b''
for _ in range(6):
    data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
    time.sleep(0.3)
open('/tmp/ha_user_graded.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
mean = [round(x,1) for x in st.mean]
# fraction of near-white pixels
px = list(im.getdata())
n = len(px)
white = sum(1 for r,g,b in px if r>245 and g>245 and b>245)
print('mean', mean, 'white_pct', round(100*white/n,1), 'size', im.size)
print('health', urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read().decode())
import subprocess
print(subprocess.getoutput("ps aux | grep 'ffmpeg.*rawvideo' | grep -v grep | head -n1"))
PY
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-whitefix")
    except OSError:
        pass
    for name, src in (
        ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
        ("camera_preview.json", ROOT / "config" / "camera_preview.json"),
    ):
        with sftp.file(f"/tmp/ha-whitefix/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/fix-white.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-white.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/fix-white.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    blob = sftp.file("/tmp/ha_user_graded.jpg", "rb").read()
    (OUT / "graded.jpg").write_bytes(blob)
    sftp.close()
    c.close()
    im = Image.open(OUT / "graded.jpg").convert("RGB")
    st = ImageStat.Stat(im)
    print("local mean", [round(x, 1) for x in st.mean], flush=True)
    if code != 0:
        raise SystemExit(code)


if __name__ == "__main__":
    main()
