#!/usr/bin/env python3
"""Time front/rear switch latency on tablet."""
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
# ensure stream has a client so switch restarts
python3 - <<'PY'
import urllib.request, threading, time
def suck():
  try:
    r = urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=30)
    r.read(4096)
    time.sleep(25)
  except Exception as e:
    print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(2)
print('client up')
PY

time_switch() {
  local face="$1"
  local t0 t1 ms
  t0=$(date +%s%3N)
  curl -fsS --max-time 30 -X POST -H 'Content-Type: application/json' \
    -d "{\"facing\":\"$face\"}" http://127.0.0.1:17824/api/input > /tmp/sw.json
  t1=$(date +%s%3N)
  ms=$((t1-t0))
  echo "switch_$face ${ms}ms $(cat /tmp/sw.json)"
}

echo === time load-atomisp ===
t0=$(date +%s%3N)
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
t1=$(date +%s%3N)
echo "load-atomisp $((t1-t0))ms"

echo === time set-input only ===
t0=$(date +%s%3N)
v4l2-ctl -d /dev/video0 --set-input=1 >/dev/null 2>&1 || true
t1=$(date +%s%3N)
echo "set-input-1 $((t1-t0))ms"
t0=$(date +%s%3N)
v4l2-ctl -d /dev/video0 --set-input=0 >/dev/null 2>&1 || true
t1=$(date +%s%3N)
echo "set-input-0 $((t1-t0))ms"

echo === API switches ===
time_switch rear
sleep 1
time_switch front
sleep 1
time_switch rear
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password="kiosk", timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_time_switch.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_time_switch.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(90)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_time_switch.sh")
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
