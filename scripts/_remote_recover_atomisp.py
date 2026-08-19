#!/usr/bin/env python3
"""Soft-recover AtomISP when sensor power -5 / REQBUFS fails."""
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
pkill -9 -f 'ffmpeg.*1600x1184' || true
sleep 1

if systemctl list-unit-files | grep -q ha-kiosk-atomisp; then
  systemctl restart ha-kiosk-atomisp.service || true
  sleep 2
fi

# Prefer existing loader (sudo path has modprobe)
if [[ -x /opt/ha-kiosk/scripts/load-atomisp.sh ]]; then
  /opt/ha-kiosk/scripts/load-atomisp.sh || true
fi

# If still wedged, bounce the modules gently
if ! v4l2-ctl -d /dev/video0 --stream-mmap=2 --stream-count=1 --stream-to=/tmp/one.nv12 2>/tmp/v4l_err.txt; then
  echo "stream failed, trying module bounce"
  cat /tmp/v4l_err.txt || true
  modprobe -r atomisp_gmin_platform || true
  modprobe -r atomisp || true
  sleep 1
  /opt/ha-kiosk/scripts/load-atomisp.sh || true
  sleep 2
fi

v4l2-ctl -d /dev/video0 --get-fmt-video || true
dmesg | tail -30
timeout -s KILL 25 v4l2-ctl -d /dev/video0 --stream-mmap=4 --stream-count=2 --stream-to=/tmp/two.nv12 || true
ls -la /tmp/two.nv12 || true
python3 - <<'PY'
import os
p='/tmp/two.nv12'
print('exists', os.path.exists(p), 'size', os.path.getsize(p) if os.path.exists(p) else 0)
if os.path.exists(p) and os.path.getsize(p):
    n=os.path.getsize(p)
    print('per_frame', n/2)
    print('size_image', 2842624, 'mod', n % 2842624)
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
    with sftp.file("/tmp/recover-atomisp.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/recover-atomisp.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/recover-atomisp.sh",
        timeout=180,
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
    try:
        sftp.get("/tmp/probe_cap.jpg", str(ROOT / "logs" / "probe_cap.jpg"))
        print("saved probe_cap.jpg", flush=True)
    except Exception as exc:
        print("no probe_cap:", exc, flush=True)
    sftp.close()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
