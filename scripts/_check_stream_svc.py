#!/usr/bin/env python3
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_st.sh", "w") as f:
    f.write(
        """#!/bin/bash
systemctl status ha-kiosk-camera-stream.service --no-pager -l | head -40
echo === JOURNAL ===
journalctl -u ha-kiosk-camera-stream.service -n 50 --no-pager -o short-iso
echo === SYNTAX ===
python3 -m py_compile /opt/ha-kiosk/scripts/camera-stream-server.py && echo py_ok
echo === MANUAL ===
timeout 5 python3 /opt/ha-kiosk/scripts/camera-stream-server.py || true
"""
    )
sftp.chmod("/tmp/_st.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(40)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_st.sh")
buf = b""
t = time.time() + 40
while time.time() < t:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode("utf-8", "replace")[-8000:])
c.close()
