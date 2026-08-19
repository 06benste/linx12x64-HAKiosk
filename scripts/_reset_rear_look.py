#!/usr/bin/env python3
"""Reset test rear look to match front so user starts clean."""
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
python3 - <<'PY'
import json
from pathlib import Path
p = Path('/opt/ha-kiosk/config/camera_preview.json')
d = json.loads(p.read_text(encoding='utf-8'))
by = d.get('software_preview_by_facing') or {}
front = by.get('front') or d.get('software_preview') or {}
# Drop rear so it inherits front until user saves a rear look
by.pop('rear', None)
if front:
    by['front'] = front
    d['software_preview'] = front
d['software_preview_by_facing'] = by
tmp = p.with_suffix('.json.tmp')
tmp.write_text(json.dumps(d, indent=2) + '\n', encoding='utf-8')
tmp.replace(p)
print('rear cleared; front_ev', front.get('exposure_ev'))
PY
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"facing":"front"}' http://127.0.0.1:17824/api/input >/dev/null
systemctl restart ha-kiosk-camera-stream.service
sleep 4
curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_reset_rear.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_reset_rear.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(40)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_reset_rear.sh")
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
