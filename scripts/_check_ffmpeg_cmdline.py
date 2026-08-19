#!/usr/bin/env python3
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_ps.sh", "w") as f:
    f.write(
        """#!/bin/bash
# wake stream
curl -fsS --max-time 2 http://127.0.0.1:17824/health; echo
python3 - <<'PY'
import urllib.request, threading, time
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=8).read(2048)
  except Exception: pass
threading.Thread(target=suck, daemon=True).start()
time.sleep(2)
print('clients ok')
PY
sleep 2
ps auxww | grep -E 'ffmpeg|v4l2-ctl|camera-stream' | grep -v grep
echo === ENV ===
systemctl show ha-kiosk-camera-stream.service -p Environment --no-pager
"""
    )
sftp.chmod("/tmp/_ps.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(30)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_ps.sh")
buf = b""
t = time.time() + 30
while time.time() < t:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode("utf-8", "replace"))
c.close()
