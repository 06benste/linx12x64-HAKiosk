#!/usr/bin/env python3
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
cmd = r"""
echo kiosk | sudo -S -p '' bash -lc '
v4l2-ctl -d /dev/video0 -l 2>&1 | head -80
echo ===
v4l2-ctl -d /dev/video0 -C low_light_mode 2>&1 || true
'
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
_, o, _ = c.exec_command(cmd, timeout=30, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
