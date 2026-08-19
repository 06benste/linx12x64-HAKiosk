#!/usr/bin/env python3
"""Deploy front/rear switch support and verify."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
install -m 755 /tmp/ha-rear/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-rear/gc2355_hw_exposure.py /opt/ha-kiosk/scripts/gc2355_hw_exposure.py
install -m 755 /tmp/ha-rear/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
install -d -m 755 /opt/ha-kiosk/config
echo 0 > /opt/ha-kiosk/config/camera_input
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service || true
for i in $(seq 1 30); do
  curl -fsS --max-time 2 http://127.0.0.1:17824/health >/dev/null && break
  sleep 1
done
python3 - <<'PY'
import io, json, time, urllib.request, threading
from PIL import Image, ImageStat

def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(2048)
    except Exception as e: print('suck', e)

def snap(name):
    threading.Thread(target=suck, daemon=True).start()
    time.sleep(4)
    data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
    open(name,'wb').write(data)
    im = Image.open(io.BytesIO(data)).convert('RGB')
    st = ImageStat.Stat(im)
    print(name, 'mean', [round(x,1) for x in st.mean], 'bytes', len(data))

print('health', urllib.request.urlopen('http://127.0.0.1:17824/health').read().decode())
print('input', urllib.request.urlopen('http://127.0.0.1:17824/api/input').read().decode())
snap('/tmp/cam_switch_front.jpg')

body=json.dumps({'facing':'rear'}).encode()
req=urllib.request.Request('http://127.0.0.1:17824/api/input', data=body, headers={'Content-Type':'application/json'}, method='POST')
print('switch', urllib.request.urlopen(req, timeout=60).read().decode())
time.sleep(2)
print('health2', urllib.request.urlopen('http://127.0.0.1:17824/health').read().decode())
snap('/tmp/cam_switch_rear.jpg')

body=json.dumps({'facing':'front'}).encode()
req=urllib.request.Request('http://127.0.0.1:17824/api/input', data=body, headers={'Content-Type':'application/json'}, method='POST')
print('switch_back', urllib.request.urlopen(req, timeout=60).read().decode())
PY
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-rear")
    except OSError:
        pass
    for name in ("camera-stream-server.py", "gc2355_hw_exposure.py", "ha-kiosk-mqtt.py"):
        with sftp.file(f"/tmp/ha-rear/{name}", "wb") as f:
            f.write((ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/deploy_facing.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy_facing.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy_facing.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    for src, dst in (("/tmp/cam_switch_front.jpg", "switch_front.jpg"), ("/tmp/cam_switch_rear.jpg", "switch_rear.jpg")):
        try:
            (OUT / dst).write_bytes(sftp.file(src, "rb").read())
            print("saved", dst)
        except Exception as e:
            print("miss", dst, e)
    sftp.close()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
