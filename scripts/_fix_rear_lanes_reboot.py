#!/usr/bin/env python3
"""Test rear input switch + stream; then rebuild with 1-lane fix and reboot."""
from __future__ import annotations

import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 1

echo '=== set-input 1 ==='
timeout -s KILL 5 v4l2-ctl -d /dev/video0 --set-input=1 2>&1 || true
v4l2-ctl -d /dev/video0 -I 2>&1 || true

dmesg -C || true
echo '=== stream rear ==='
timeout -s KILL 18 v4l2-ctl -d /dev/video0 --set-input=1 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=3 --stream-count=6 --stream-to=/tmp/cam_rear.raw 2>&1 || true
ls -la /tmp/cam_rear.raw || true
echo '=== dmesg ==='
dmesg | tail -n 80

echo '=== patch lanes + rebuild ==='
python3 /tmp/ha-rear/_patch_gmin_linx_csi_lanes.py
KVER=$(uname -r)
dkms build -m atomisp-6.10 -v 1.0.3-linx -k "$KVER"
dkms install -m atomisp-6.10 -v 1.0.3-linx -k "$KVER" --force
echo REBOOTING
reboot
"""

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
with sftp.file("/tmp/rear_fix.sh", "w") as f:
    f.write(REMOTE.replace("\r\n", "\n"))
sftp.chmod("/tmp/rear_fix.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/rear_fix.sh", timeout=900, get_pty=True)
# reboot will kill connection; read what we can
try:
    print(o.read().decode("utf-8", "replace"))
except Exception as e:
    print("conn closed", e)
c.close()

print("waiting for reboot...")
for i in range(36):
    time.sleep(5)
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username="kioskuser", password=PASS, timeout=8, allow_agent=False, look_for_keys=False)
        _, o, _ = c.exec_command("uptime; dmesg | grep -iE 'LINX_CSI|detected .*camera|camera pdata' | tail -n 20", timeout=30)
        print(o.read().decode())
        c.close()
        print("BACK")
        break
    except Exception as e:
        print("wait", i, type(e).__name__)
else:
    raise SystemExit("no come back")
