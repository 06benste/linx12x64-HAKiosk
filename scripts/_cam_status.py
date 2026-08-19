#!/usr/bin/env python3
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
echo === status ===
systemctl is-active ha-kiosk-camera-stream.service || true
grep CAMERA_STREAM /opt/ha-kiosk/mqtt.env || true
systemctl show ha-kiosk-camera-stream.service -p Environment --no-pager | tr ' ' '\n' | grep CAMERA || true
curl -fsS --max-time 3 http://127.0.0.1:17824/health || echo health_fail
echo
echo === journal ===
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager || true
echo === quick stream test ===
python3 - <<'PY'
import json, threading, time, urllib.request
n=[0]; err=['']; stop=[False]
def suck():
  try:
    r=urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=30)
    buf=b''
    end=time.time()+10
    while time.time()<end and not stop[0]:
      c=r.read(16384)
      if not c: break
      buf+=c
      while True:
        a=buf.find(b'\xff\xd8')
        if a<0:
          buf=buf[-1:]; break
        b=buf.find(b'\xff\xd9', a+2)
        if b<0:
          buf=buf[a:]; break
        n[0]+=1
        buf=buf[b+2:]
  except Exception as e:
    err[0]=repr(e)
th=threading.Thread(target=suck, daemon=True); th.start(); th.join(12); stop[0]=True
try:
  h=json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=3).read())
except Exception as e:
  h={'error':str(e)}
print('jpegs', n[0], 'err', err[0], 'health', h)
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_cam_status.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_cam_status.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(60)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_cam_status.sh")
buf = b""
deadline = time.time() + 60
while time.time() < deadline:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode(errors="replace"))
c.close()
