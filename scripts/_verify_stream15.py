#!/usr/bin/env python3
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
python3 - <<'PY'
import json, threading, time, urllib.request
n=[0]; err=['']; stop=[False]
def suck():
  try:
    r=urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=30)
    buf=b''; end=time.time()+8
    while time.time()<end and not stop[0]:
      c=r.read(16384)
      if not c: break
      buf+=c
      while True:
        a=buf.find(b'\xff\xd8')
        if a<0: buf=buf[-1:]; break
        b=buf.find(b'\xff\xd9', a+2)
        if b<0: buf=buf[a:]; break
        n[0]+=1; buf=buf[b+2:]
  except Exception as e:
    err[0]=repr(e)
th=threading.Thread(target=suck, daemon=True); th.start(); th.join(10); stop[0]=True
h=json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=3).read())
print('jpegs', n[0], 'approx_fps', round(n[0]/8, 2), 'cfg', h.get('fps'), 'frames', h.get('frames'), 'restarts', h.get('restarts'), 'err', err[0])
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_verify_stream.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_verify_stream.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(40)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_verify_stream.sh")
buf = b""
deadline = time.time() + 40
while time.time() < deadline:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
import sys
sys.stdout.buffer.write(buf)
c.close()
