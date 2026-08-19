#!/usr/bin/env python3
"""Diag rear stream hang + optional 1-lane rebuild."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
DO_REBUILD = "--rebuild" in sys.argv

REMOTE = r"""
set -euxo pipefail
DO_REBUILD=__DO_REBUILD__

systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 1

if [[ "$DO_REBUILD" == "1" ]]; then
  python3 /tmp/ha-rear/_patch_gmin_linx_csi_lanes.py
  KVER=$(uname -r)
  MOD=atomisp-6.10
  VER=1.0.3-linx
  dkms build -m $MOD -v $VER -k "$KVER"
  dkms install -m $MOD -v $VER -k "$KVER" --force
  echo REBOOT_NEEDED
  reboot
  exit 0
fi

# Live diag without rebuild first
dmesg -C || true
echo '=== try rear with verbose ==='
timeout -s KILL 20 v4l2-ctl -d /dev/video0 --set-input=1 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=5 --stream-to=/tmp/cam_rear.raw -v 2>&1 | tail -n 80 || true
ls -la /tmp/cam_rear.raw 2>/dev/null || true
echo '=== dmesg during rear ==='
dmesg | grep -iE 'gc2235|atomisp|error|fail|timeout|CSI|stream' | tail -n 60

# Also try switching input then streaming
echo '=== set-input 1 then stream ==='
v4l2-ctl -d /dev/video0 --set-input=1 2>&1 || true
sleep 1
timeout -s KILL 12 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=3 --stream-count=5 --stream-to=/tmp/cam_rear2.raw 2>&1 | tail -n 40 || true
ls -la /tmp/cam_rear2.raw 2>/dev/null || true
dmesg | grep -iE 'gc2235|atomisp|error|fail|LINX' | tail -n 40

v4l2-ctl -d /dev/video0 --set-input=0 2>/dev/null || true
systemctl start ha-kiosk-camera-stream.service || true
""".replace("__DO_REBUILD__", "1" if DO_REBUILD else "0")


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-rear")
    except OSError:
        pass
    with sftp.file("/tmp/ha-rear/_patch_gmin_linx_csi_lanes.py", "wb") as f:
        f.write((ROOT / "scripts/_patch_gmin_linx_csi_lanes.py").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/rear_diag.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/rear_diag.sh", 0o755)
    sftp.close()
    timeout = 900 if DO_REBUILD else 120
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/rear_diag.sh", timeout=timeout, get_pty=True)
    try:
        print(o.read().decode("utf-8", "replace"))
    except Exception as e:
        print("read err", e)
    c.close()


if __name__ == "__main__":
    main()
