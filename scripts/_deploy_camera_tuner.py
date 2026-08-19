#!/usr/bin/env python3
"""Deploy camera tuner (stream API + HTML + dock + CLI) to the tablet."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -d -m 755 /opt/ha-kiosk/scripts/static /opt/ha-kiosk/bin
install -m 755 /tmp/ha-tuner/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-tuner/cam-tuner.html /opt/ha-kiosk/scripts/static/cam-tuner.html
install -m 755 /tmp/ha-tuner/ha-cam-tuner /opt/ha-kiosk/bin/ha-cam-tuner
install -m 755 /tmp/ha-tuner/ha-cam-tuner /opt/ha-kiosk/scripts/ha-cam-tuner
ln -sfn /opt/ha-kiosk/bin/ha-cam-tuner /usr/local/bin/ha-cam-tuner
install -m 644 /tmp/ha-tuner/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 644 /tmp/ha-tuner/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
chown -R kioskuser:kioskuser /opt/ha-kiosk/chromium-extension /opt/ha-kiosk/scripts/static
systemctl restart ha-kiosk-camera-stream.service
# Soft-reload extension by restarting kiosk session
systemctl restart getty@tty1.service
sleep 4
for i in $(seq 1 25); do
  if curl -fsS --max-time 2 http://127.0.0.1:17824/health >/dev/null; then break; fi
  sleep 1
done
curl -fsS --max-time 5 http://127.0.0.1:17824/api/look | head -c 400; echo
curl -fsS --max-time 5 -o /dev/null -w 'tuner_html=%{http_code}\n' http://127.0.0.1:17824/tuner
# Wake stream briefly
python3 - <<'PY'
import json, time, urllib.request, threading
def suck():
    try:
        urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg?plain=1', timeout=15).read(256)
    except Exception as e:
        print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
print('health', h)
look = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/api/look', timeout=5).read())
print('look_ok', look.get('ok'), list((look.get('software_preview') or {}).keys()))
# Save round-trip (same values)
body = json.dumps({'software_preview': look['software_preview']}).encode()
req = urllib.request.Request('http://127.0.0.1:17824/api/look', data=body, headers={'Content-Type':'application/json'}, method='POST')
resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
print('save', resp.get('ok'), resp.get('message'))
time.sleep(2)
h2 = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
print('health_after_save', h2.get('streaming'), h2.get('frames'), h2.get('look',{}).get('exposure_ev'))
print('which_cli', __import__('subprocess').getoutput('which ha-cam-tuner; ls -l /opt/ha-kiosk/bin/ha-cam-tuner'))
PY
echo DEPLOY_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-tuner")
    except OSError:
        pass
    files = {
        "camera-stream-server.py": ROOT / "scripts" / "camera-stream-server.py",
        "cam-tuner.html": ROOT / "scripts" / "static" / "cam-tuner.html",
        "ha-cam-tuner": ROOT / "scripts" / "ha-cam-tuner",
        "power-drawer.js": ROOT / "chromium-extension" / "power-drawer.js",
        "manifest.json": ROOT / "chromium-extension" / "manifest.json",
    }
    for name, src in files.items():
        with sftp.file(f"/tmp/ha-tuner/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
        print("up", name, flush=True)
    with sftp.file("/tmp/deploy-tuner.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-tuner.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-tuner.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
