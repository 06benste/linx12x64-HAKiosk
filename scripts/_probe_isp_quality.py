#!/usr/bin/env python3
"""Probe AtomISP / video controls and firmware on the tablet."""
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
CMD = r"""
set -e
echo '=== modules ==='
lsmod | grep -iE 'atomisp|gc22|ov56' || true
echo '=== firmware ==='
ls -la /lib/firmware/intel/atomisp/* 2>/dev/null | head -40 || ls -la /lib/firmware/*atomisp* 2>/dev/null | head -40 || true
echo '=== dmesg atomisp ==='
dmesg | grep -iE 'atomisp|gc2235|gc2355|isp240|shading|3a|css' | tail -n 60 || true
echo '=== stop stream briefly for ctrls ==='
systemctl stop ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 0.5
echo '=== v4l2 ctrls ==='
v4l2-ctl -d /dev/video0 -l 2>&1 | head -120 || true
echo '=== v4l2 all head ==='
v4l2-ctl -d /dev/video0 --all 2>&1 | head -100 || true
echo '=== formats ==='
v4l2-ctl -d /dev/video0 --list-formats-ext 2>&1 | head -80 || true
echo '=== restart stream ==='
systemctl start ha-kiosk-camera-stream.service || true
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/probe_isp.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/probe_isp.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/probe_isp.sh", timeout=120, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
