#!/usr/bin/env python3
"""Deploy fast camera switch and re-time."""
import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")

SCRIPT = r"""
set -e
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/cam-tuner.html /opt/ha-kiosk/scripts/static/cam-tuner.html
systemctl restart ha-kiosk-camera-stream.service
sleep 5
systemctl is-active ha-kiosk-camera-stream.service

python3 - <<'PY'
import urllib.request, threading, time
def suck():
  try:
    r = urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=60)
    r.read(4096)
    time.sleep(40)
  except Exception as e:
    print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(2)
print('client up')
PY

time_switch() {
  local face="$1"
  local t0 t1
  t0=$(date +%s%3N)
  curl -fsS --max-time 20 -X POST -H 'Content-Type: application/json' \
    -d "{\"facing\":\"$face\"}" http://127.0.0.1:17824/api/input > /tmp/sw.json
  t1=$(date +%s%3N)
  echo "switch_$face $((t1-t0))ms $(cat /tmp/sw.json)"
  sleep 0.8
  curl -fsS --max-time 3 http://127.0.0.1:17824/health; echo
}

time_switch rear
time_switch front
time_switch rear
time_switch front
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
for name, local in [
    ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
    ("cam-tuner.html", ROOT / "scripts" / "static" / "cam-tuner.html"),
]:
    with sftp.file(f"/tmp/{name}", "wb") as f:
        f.write(local.read_bytes().replace(b"\r\n", b"\n"))
with sftp.file("/tmp/_deploy_fast_switch.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_deploy_fast_switch.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(90)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_deploy_fast_switch.sh")
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
print("\nexit", chan.recv_exit_status() if chan.exit_status_ready() else "?")
c.close()
