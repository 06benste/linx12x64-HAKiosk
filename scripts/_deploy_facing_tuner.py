#!/usr/bin/env python3
"""Deploy camera facing toggle + per-camera looks to tablet."""
import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")

SCRIPT = r"""
set -e
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -d /opt/ha-kiosk/scripts/static
install -m 644 /tmp/cam-tuner.html /opt/ha-kiosk/scripts/static/cam-tuner.html
# Merge by_facing into existing config without wiping rear if already present
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/opt/ha-kiosk/config/camera_preview.json')
data = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
sp = data.get('software_preview') if isinstance(data.get('software_preview'), dict) else {}
by = data.get('software_preview_by_facing')
if not isinstance(by, dict):
    by = {}
if 'front' not in by and sp:
    by['front'] = dict(sp)
data['software_preview_by_facing'] = by
if sp:
    data['software_preview'] = sp
tmp = p.with_suffix('.json.tmp')
tmp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
tmp.replace(p)
print('config ok keys', list(by.keys()))
PY
systemctl restart ha-kiosk-camera-stream.service
sleep 5
systemctl is-active ha-kiosk-camera-stream.service
echo === health ===
curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo
echo === look api ===
curl -fsS --max-time 4 'http://127.0.0.1:17824/api/look'; echo
echo === input api ===
curl -fsS --max-time 4 'http://127.0.0.1:17824/api/input'; echo
echo === switch rear ===
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' \
  -d '{"facing":"rear"}' http://127.0.0.1:17824/api/input; echo
sleep 3
curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo
curl -fsS --max-time 4 'http://127.0.0.1:17824/api/look'; echo
echo === switch front ===
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' \
  -d '{"facing":"front"}' http://127.0.0.1:17824/api/input; echo
sleep 2
curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo
echo === tuner has facing buttons ===
grep -c 'btn-rear' /opt/ha-kiosk/scripts/static/cam-tuner.html
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
for name, local in [
    ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
    ("cam-tuner.html", ROOT / "scripts" / "static" / "cam-tuner.html"),
]:
    with sftp.file(f"/tmp/{name}", "wb") as f:
        f.write(local.read_bytes().replace(b"\r\n", b"\n"))
with sftp.file("/tmp/_deploy_facing.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_deploy_facing.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(90)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_deploy_facing.sh")
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
