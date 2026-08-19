#!/usr/bin/env python3
"""Deploy higher FPS / lower-lag stream settings and measure achieved rate."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 755 /tmp/ha-fps/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-fps/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
install -m 644 /tmp/ha-fps/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service

# Bump MQTT republish FPS in live mqtt.env (keep other keys).
python3 - <<'PY'
from pathlib import Path
p = Path('/opt/ha-kiosk/mqtt.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
lines = [ln for ln in text.splitlines() if not ln.startswith('CAMERA_STREAM_MQTT_FPS=') and not ln.startswith('CAMERA_STREAM_FPS=') and not ln.startswith('CAMERA_STREAM_WIDTH=') and not ln.startswith('CAMERA_STREAM_HEIGHT=')]
# Stream geometry/FPS come from the systemd unit; only MQTT fps must live in mqtt.env
# (mqtt service EnvironmentFile). Keep a comment for clarity.
if not any(ln.startswith('CAMERA_STREAM_MQTT=') for ln in lines):
    lines.append('CAMERA_STREAM_MQTT=1')
lines.append('CAMERA_STREAM_MQTT_FPS=6')
p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
print('mqtt.env stream keys:')
print('\n'.join(ln for ln in p.read_text().splitlines() if 'CAMERA_STREAM' in ln or 'MQTT_FPS' in ln))
PY

systemctl daemon-reload
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service

for i in $(seq 1 25); do
  if curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:17824/health; then break; fi
  sleep 1
done

# Wake capture via a short stream client, then measure frame rate from /health.
python3 - <<'PY'
import json, time, urllib.request, threading

def suck():
    try:
        urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(256)
    except Exception:
        pass

threading.Thread(target=suck, daemon=True).start()
time.sleep(2.5)
h1 = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
time.sleep(5.0)
h2 = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
df = max(0, int(h2.get('frames', 0)) - int(h1.get('frames', 0)))
print('health1', h1)
print('health2', h2)
print(f'measured_fps≈{df/5.0:.2f} over 5s (frames_delta={df})')
PY

systemctl show ha-kiosk-camera-stream -p Environment --no-pager
ps aux | grep -E 'ffmpeg.*rawvideo|camera-stream' | grep -v grep || true
journalctl -u ha-kiosk-mqtt -n 8 --no-pager | tail -n 8
journalctl -u ha-kiosk-camera-stream -n 8 --no-pager | tail -n 8
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-fps")
    except OSError:
        pass
    for name in (
        "camera-stream-server.py",
        "ha-kiosk-mqtt.py",
        "ha-kiosk-camera-stream.service",
    ):
        src = ROOT / "scripts" / name
        with sftp.file(f"/tmp/ha-fps/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
        print("up", name, flush=True)
    with sftp.file("/tmp/deploy-fps.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-fps.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-fps.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    if o.channel.recv_exit_status() != 0:
        raise SystemExit(1)
    c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
