#!/usr/bin/env python3
"""Probe rear camera / AtomISP dual-sensor state on the tablet."""
from __future__ import annotations

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

CMD = r"""
set -euxo pipefail
modprobe i2c-dev || true
echo '=== modules ==='
lsmod | grep -iE 'atomisp|gc22' || true
echo '=== devices ==='
v4l2-ctl --list-devices 2>&1 || true
ls -l /dev/video* /dev/v4l-subdev* /dev/media* 2>/dev/null || true
echo '=== media topology (short) ==='
media-ctl -p -d /dev/media0 2>&1 | head -n 120 || true
echo '=== i2c sensors ==='
for d in /sys/bus/i2c/devices/i2c-GCTI2355:*; do
  echo "-- $d"
  readlink -f "$d" || true
  cat "$d/name" 2>/dev/null || true
  cat "$d/power/runtime_status" 2>/dev/null || true
done
echo '=== dmesg sensors ==='
dmesg | grep -iE 'gc2235|gc2355|GCTI|CsiPort|LINX_CSI|detected .*camera|port .*sensor|already has' | tail -n 80
echo '=== gmin quirk in source ==='
grep -n 'GCTI2355.*CsiPort\|LINX_CSI' /usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c 2>/dev/null | head -n 40 || true
echo '=== video inputs ==='
# stop stream briefly so we can query inputs
systemctl stop ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 0.5
v4l2-ctl -d /dev/video0 --list-inputs 2>&1 || true
v4l2-ctl -d /dev/video0 --all 2>&1 | head -n 80 || true
echo '=== try input 0 capture ==='
timeout -s KILL 8 v4l2-ctl -d /dev/video0 --set-input=0 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --stream-mmap=2 --stream-count=5 --stream-to=/tmp/cam0.raw 2>&1 | tail -n 20 || true
ls -la /tmp/cam0.raw 2>/dev/null || true
echo '=== try input 1 capture ==='
timeout -s KILL 8 v4l2-ctl -d /dev/video0 --set-input=1 --set-fmt-video=width=1600,height=1200,pixelformat=NV12 --stream-mmap=2 --stream-count=5 --stream-to=/tmp/cam1.raw 2>&1 | tail -n 30 || true
ls -la /tmp/cam1.raw 2>/dev/null || true
echo '=== inputs after ==='
v4l2-ctl -d /dev/video0 --list-inputs 2>&1 || true
v4l2-ctl -d /dev/video0 -I 2>&1 || true
systemctl start ha-kiosk-camera-stream.service || true
echo PROBE_DONE
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/probe_rear.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/probe_rear.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/probe_rear.sh", timeout=120, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
