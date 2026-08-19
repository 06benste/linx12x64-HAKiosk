#!/usr/bin/env python3
"""Deploy: no wrap, MQTT fps=1, stream fps=8."""
import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")

SCRIPT = r"""
set -e
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 755 /tmp/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
install -m 644 /tmp/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service

# mqtt.env: force FPS settings
python3 - <<'PY'
from pathlib import Path
p = Path('/opt/ha-kiosk/mqtt.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
lines = []
seen = set()
for raw in text.splitlines():
    if not raw.strip() or raw.lstrip().startswith('#') or '=' not in raw:
        lines.append(raw)
        continue
    k = raw.split('=', 1)[0].strip()
    if k in ('CAMERA_STREAM_MQTT_FPS', 'CAMERA_STREAM_FPS'):
        continue
    lines.append(raw)
    seen.add(k)
lines.append('CAMERA_STREAM_MQTT_FPS=1')
lines.append('CAMERA_STREAM_FPS=8')
p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
print('mqtt.env updated')
for ln in p.read_text(encoding='utf-8').splitlines():
    if 'CAMERA_STREAM' in ln or 'SCREENSHOT' in ln:
        print(' ', ln)
PY

# remove wrap drop-in
rm -f /etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf
rmdir /etc/systemd/system/ha-kiosk-camera-stream.service.d 2>/dev/null || true

systemctl daemon-reload
systemctl kill -s SIGTERM ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f camera-stream-server.py || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo.*1600x1184' || true
sleep 1
systemctl reset-failed ha-kiosk-camera-stream.service || true
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service
sleep 7
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service
echo === env ===
systemctl show ha-kiosk-camera-stream.service -p Environment --no-pager
echo === health ===
curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo
echo === no wrap in ffmpeg ===
sleep 2
# wake briefly
python3 - <<'PY'
import urllib.request, threading, time
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=8).read(2048)
  except Exception: pass
threading.Thread(target=suck, daemon=True).start()
time.sleep(2)
PY
ps auxww | grep '[f]fmpeg' || true
echo === snapshot rate 8s ===
n=$(journalctl -u ha-kiosk-camera-stream.service --since '8 seconds ago' --no-pager | grep -c snapshot || true)
echo "snapshot_hits=$n"
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
for name, local in [
    ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
    ("ha-kiosk-mqtt.py", ROOT / "scripts" / "ha-kiosk-mqtt.py"),
    ("ha-kiosk-camera-stream.service", ROOT / "scripts" / "ha-kiosk-camera-stream.service"),
]:
    with sftp.file(f"/tmp/{name}", "wb") as f:
        f.write(local.read_bytes().replace(b"\r\n", b"\n"))
with sftp.file("/tmp/_deploy_load.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_deploy_load.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(70)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_deploy_load.sh")
buf = b""
deadline = time.time() + 70
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
