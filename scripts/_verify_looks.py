#!/usr/bin/env python3
"""Confirm per-facing look save keeps front/rear independent."""
import json
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
# ensure front, save a marker on rear only
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"facing":"front"}' http://127.0.0.1:17824/api/input >/tmp/in.json
sleep 2
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' \
  -d '{"facing":"rear","software_preview":{"exposure_ev":1.25,"contrast":1.2,"saturation":1.1,"wb_r":1.2,"wb_g":1.0,"wb_b":1.1,"shadows":0.1,"highlights":0.05}}' \
  http://127.0.0.1:17824/api/look; echo
python3 - <<'PY'
import json
from pathlib import Path
d=json.loads(Path('/opt/ha-kiosk/config/camera_preview.json').read_text())
by=d.get('software_preview_by_facing',{})
print('front_ev', by.get('front',{}).get('exposure_ev'), 'rear_ev', by.get('rear',{}).get('exposure_ev'))
print('legacy_ev', d.get('software_preview',{}).get('exposure_ev'))
PY
# switch to rear and confirm look api
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"facing":"rear"}' http://127.0.0.1:17824/api/input; echo
sleep 2
curl -fsS --max-time 4 'http://127.0.0.1:17824/api/look' | python3 -c 'import sys,json; d=json.load(sys.stdin); print("active", d["facing"], "ev", d["software_preview"]["exposure_ev"])'
# back to front
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"facing":"front"}' http://127.0.0.1:17824/api/input >/dev/null
sleep 2
curl -fsS --max-time 4 'http://127.0.0.1:17824/api/look' | python3 -c 'import sys,json; d=json.load(sys.stdin); print("active", d["facing"], "ev", d["software_preview"]["exposure_ev"])'
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_verify_looks.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_verify_looks.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(60)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_verify_looks.sh")
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
import sys
sys.stdout.buffer.write(buf)
c.close()
