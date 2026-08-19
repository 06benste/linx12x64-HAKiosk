#!/usr/bin/env python3
"""Deploy MJPEG-as-live path: FPS=15, mqtt stills naming, recover if wedged."""
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

python3 - <<'PY'
from pathlib import Path
p = Path('/opt/ha-kiosk/mqtt.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
lines = []
for raw in text.splitlines():
    if not raw.strip() or raw.lstrip().startswith('#') or '=' not in raw:
        lines.append(raw)
        continue
    k = raw.split('=', 1)[0].strip()
    if k in ('CAMERA_STREAM_FPS', 'CAMERA_STREAM_MQTT_FPS', 'CAMERA_STREAM_QUALITY', 'CAMERA_STREAM_V4L_BUFFERS'):
        continue
    lines.append(raw)
lines.append('CAMERA_STREAM_FPS=15')
lines.append('CAMERA_STREAM_QUALITY=6')
lines.append('CAMERA_STREAM_V4L_BUFFERS=4')
lines.append('CAMERA_STREAM_MQTT_FPS=1')
p.write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')
print('mqtt.env ok')
PY

# clear any experimental fps drop-in
rm -f /etc/systemd/system/ha-kiosk-camera-stream.service.d/fps.conf
rmdir /etc/systemd/system/ha-kiosk-camera-stream.service.d 2>/dev/null || true

systemctl daemon-reload
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service
for i in $(seq 1 25); do
  if curl -fsS --max-time 1 http://127.0.0.1:17824/health >/tmp/h.json 2>/dev/null; then
    break
  fi
  sleep 0.4
done
echo === health ===
cat /tmp/h.json; echo
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service
echo === one-connection stream sample ===
python3 - <<'PY'
import json, threading, time, urllib.request
n=[0]; stop=[False]
def suck():
  try:
    r=urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=30)
    buf=b''
    end=time.time()+6
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
    print('stream_err', e)
th=threading.Thread(target=suck, daemon=True); th.start(); th.join(8); stop[0]=True
h=json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=3).read())
print('jpegs_in_6s', n[0], 'approx_fps', round(n[0]/6, 2), 'configured', h.get('fps'), 'frames', h.get('frames'), 'restarts', h.get('restarts'))
PY
uptime
"""

def main() -> None:
    last_err = None
    for attempt in range(8):
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(
                HOST,
                username="kioskuser",
                password=PASS,
                timeout=12,
                allow_agent=False,
                look_for_keys=False,
                banner_timeout=12,
            )
            sftp = c.open_sftp()
            for name, local in [
                ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
                ("ha-kiosk-mqtt.py", ROOT / "scripts" / "ha-kiosk-mqtt.py"),
                ("ha-kiosk-camera-stream.service", ROOT / "scripts" / "ha-kiosk-camera-stream.service"),
            ]:
                with sftp.file(f"/tmp/{name}", "wb") as f:
                    f.write(local.read_bytes().replace(b"\r\n", b"\n"))
            with sftp.file("/tmp/_deploy_mjpeg_live.sh", "w") as f:
                f.write(SCRIPT)
            sftp.chmod("/tmp/_deploy_mjpeg_live.sh", 0o755)
            sftp.close()
            chan = c.get_transport().open_session()
            chan.settimeout(90)
            chan.get_pty()
            chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_deploy_mjpeg_live.sh")
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
            print(buf.decode(errors="replace"))
            print("exit", chan.recv_exit_status() if chan.exit_status_ready() else "?")
            c.close()
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"attempt {attempt+1}: {exc}")
            time.sleep(4)
    raise SystemExit(f"deploy failed: {last_err}")


if __name__ == "__main__":
    main()
