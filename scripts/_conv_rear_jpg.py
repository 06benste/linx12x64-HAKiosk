#!/usr/bin/env python3
"""Pull rear raw, convert properly, check front stream health."""
from __future__ import annotations

import pathlib

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"

CMD = r"""
set -euxo pipefail
python3 - <<'PY'
from pathlib import Path
import subprocess
raw = Path('/tmp/cam_rear.raw').read_bytes()
fs = 2842624
assert len(raw) >= fs, len(raw)
Path('/tmp/cam_rear_one.raw').write_bytes(raw[:fs])
print('wrote frame', fs)
subprocess.check_call([
  'ffmpeg','-y','-hide_banner','-loglevel','error',
  '-f','rawvideo','-pix_fmt','nv12','-video_size','1600x1184',
  '-i','/tmp/cam_rear_one.raw',
  '-vf','crop=1584:1184:0:0,scale=800:600',
  '-frames:v','1','/tmp/cam_rear.jpg'
])
print('jpg', Path('/tmp/cam_rear.jpg').stat().st_size)
PY
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
echo
v4l2-ctl -d /dev/video0 -I 2>&1 || true
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/conv_rear.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/conv_rear.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/conv_rear.sh", timeout=60, get_pty=True)
print(o.read().decode("utf-8", "replace"))
sftp = c.open_sftp()
(OUT / "rear.jpg").write_bytes(sftp.file("/tmp/cam_rear.jpg", "rb").read())
print("saved", (OUT / "rear.jpg").stat().st_size)
sftp.close()
c.close()
