#!/usr/bin/env python3
"""Hard module bounce for wedged AtomISP (sensor power -5)."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
systemctl stop ha-kiosk-camera-stream.service || true
systemctl stop ha-kiosk-mqtt.service || true
pkill -9 -f v4l2-ctl || true
pkill -9 -f ffmpeg || true
sleep 1

echo "=== modules before ==="
lsmod | grep -iE 'atom|gc22|gc23' || true

# Unload in dependency order (best-effort)
for m in atomisp_gmin_platform atomisp_css2401a0_v21 atomisp; do
  modprobe -r "$m" 2>/dev/null || rmmod "$m" 2>/dev/null || true
done
# sensor i2c drivers often named gc2235 / atomisp_gc2235
for m in $(lsmod | awk '/gc22|gc23|atomisp/{print $1}'); do
  modprobe -r "$m" 2>/dev/null || rmmod "$m" 2>/dev/null || true
done
sleep 2

echo "=== modules after unload ==="
lsmod | grep -iE 'atom|gc22|gc23' || true

/opt/ha-kiosk/scripts/load-atomisp.sh
sleep 3

echo "=== modules after load ==="
lsmod | grep -iE 'atom|gc22|gc23' || true
ls -la /dev/video0 /dev/media0 || true
v4l2-ctl -d /dev/video0 --get-fmt-video || true
dmesg | tail -50

rm -f /tmp/two.nv12 /tmp/probe_cap.jpg
timeout -s KILL 30 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=2 --stream-to=/tmp/two.nv12 || true
ls -la /tmp/two.nv12 || true
python3 - <<'PY'
import os
p='/tmp/two.nv12'
n=os.path.getsize(p) if os.path.exists(p) else 0
print('raw_bytes', n)
if n:
    print('frames_at_2842624', n/2842624)
    print('mod', n % 2842624)
PY
/opt/ha-kiosk/scripts/capture-tablet-cam.py /tmp/probe_cap.jpg || true
ls -la /tmp/probe_cap.jpg || true
systemctl start ha-kiosk-mqtt.service || true
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/bounce-atomisp.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/bounce-atomisp.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/bounce-atomisp.sh",
        timeout=240,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    code = stdout.channel.recv_exit_status()
    sftp = c.open_sftp()
    for remote, local in (
        ("/tmp/probe_cap.jpg", ROOT / "logs" / "probe_cap.jpg"),
        ("/tmp/two.nv12", ROOT / "logs" / "two.nv12"),
    ):
        try:
            sftp.get(remote, str(local))
            print("saved", local, flush=True)
        except Exception as exc:
            print("skip", remote, exc, flush=True)
    sftp.close()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
