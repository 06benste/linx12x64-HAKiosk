#!/usr/bin/env python3
"""Diagnose stream frame delivery at a given FPS."""
import time

import paramiko

PASS = "kiosk"
FPS = 15

SCRIPT = f"""
set -e
python3 - <<'PY'
from pathlib import Path
p = Path('/opt/ha-kiosk/mqtt.env')
lines = [ln for ln in p.read_text().splitlines() if not ln.startswith('CAMERA_STREAM_FPS=')]
lines.append('CAMERA_STREAM_FPS={FPS}')
p.write_text('\\n'.join(lines)+'\\n')
PY
printf '%s\\n' '[Service]' 'Environment=CAMERA_STREAM_FPS={FPS}' > /etc/systemd/system/ha-kiosk-camera-stream.service.d/fps.conf
systemctl daemon-reload
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 30); do curl -fsS --max-time 1 http://127.0.0.1:17824/health >/dev/null 2>&1 && break; sleep 0.4; done
echo === start client + wait ===
python3 - <<'PY'
import json, threading, time, urllib.request
stop=False
n=[0]
def suck():
  global stop
  try:
    r=urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=45)
    buf=b''
    while not stop:
      c=r.read(16384)
      if not c: break
      buf+=c
      while True:
        a=buf.find(b'\\xff\\xd8');
        if a<0: buf=buf[-1:]; break
        b=buf.find(b'\\xff\\xd9',a+2)
        if b<0: buf=buf[a:]; break
        n[0]+=1; buf=buf[b+2:]
  except Exception as e:
    print('ERR',e)
th=threading.Thread(target=suck,daemon=True); th.start()
for i in range(12):
  time.sleep(1)
  try:
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health',timeout=2).read())
  except Exception as e:
    print(i,'health fail',e); continue
  print(i,'jpeg',n[0],'streaming',h.get('streaming'),'clients',h.get('clients'),'frames',h.get('frames'),'age',h.get('last_frame_age_s'),'restarts',h.get('restarts'),'err',h.get('last_error'))
stop=True
print('total_jpeg',n[0])
PY
echo === journal ===
journalctl -u ha-kiosk-camera-stream.service -n 30 --no-pager
echo === procs ===
ps auxww | grep -E '[f]fmpeg|[v]4l2-ctl' || true
""".replace("{FPS}", str(FPS))

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_diag_fps.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_diag_fps.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(90)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_diag_fps.sh")
buf = b""
deadline = time.time() + 90
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
