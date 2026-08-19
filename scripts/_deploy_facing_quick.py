#!/usr/bin/env python3
import json
import time
import urllib.request

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)

# Check if deploy finished / services
_, o, _ = c.exec_command(
    f"echo {PASS} | sudo -S -p '' bash -lc '"
    "systemctl is-active ha-kiosk-camera-stream.service; "
    "curl -fsS --max-time 3 http://127.0.0.1:17824/health || echo HEALTH_FAIL; "
    "ls -la /opt/ha-kiosk/scripts/camera-stream-server.py; "
    "grep -n set_input /opt/ha-kiosk/scripts/camera-stream-server.py | head'",
    timeout=40,
    get_pty=True,
)
print(o.read().decode())

# If not deployed, install quickly
sftp = c.open_sftp()
import pathlib
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
for name in ("camera-stream-server.py", "gc2355_hw_exposure.py", "ha-kiosk-mqtt.py"):
    with sftp.file(f"/tmp/{name}", "wb") as f:
        f.write((ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
sftp.close()

_, o, _ = c.exec_command(
    f"echo {PASS} | sudo -S -p '' bash -lc '"
    "install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py; "
    "install -m 644 /tmp/gc2355_hw_exposure.py /opt/ha-kiosk/scripts/gc2355_hw_exposure.py; "
    "install -m 755 /tmp/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py; "
    "echo 0 > /opt/ha-kiosk/config/camera_input; "
    "systemctl restart ha-kiosk-camera-stream.service; "
    "systemctl restart ha-kiosk-mqtt.service; "
    "sleep 6; curl -fsS http://127.0.0.1:17824/health'",
    timeout=60,
    get_pty=True,
)
print("deploy", o.read().decode())

# Test switch via remote python with shorter waits
remote = r'''
python3 - <<'PY'
import json, time, urllib.request, threading
from PIL import Image, ImageStat
import io

def wake():
    def suck():
        try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=15).read(1024)
        except Exception: pass
    threading.Thread(target=suck, daemon=True).start()

def snap(path):
    wake(); time.sleep(3)
    data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
    open(path,'wb').write(data)
    im=Image.open(io.BytesIO(data)).convert('RGB')
    print(path, [round(x,1) for x in ImageStat.Stat(im).mean], len(data))

print('in', urllib.request.urlopen('http://127.0.0.1:17824/api/input').read().decode())
snap('/tmp/sw_front.jpg')
body=json.dumps({'facing':'rear'}).encode()
req=urllib.request.Request('http://127.0.0.1:17824/api/input', data=body, headers={'Content-Type':'application/json'}, method='POST')
print('to_rear', urllib.request.urlopen(req, timeout=90).read().decode())
time.sleep(1)
print('h', urllib.request.urlopen('http://127.0.0.1:17824/health').read().decode())
snap('/tmp/sw_rear.jpg')
body=json.dumps({'facing':'front'}).encode()
req=urllib.request.Request('http://127.0.0.1:17824/api/input', data=body, headers={'Content-Type':'application/json'}, method='POST')
print('to_front', urllib.request.urlopen(req, timeout=90).read().decode())
print('DONE')
PY
'''
sftp = c.open_sftp()
with sftp.file('/tmp/swtest.sh','w') as f:
    f.write(remote)
sftp.chmod('/tmp/swtest.sh', 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/swtest.sh", timeout=180, get_pty=True)
print(o.read().decode())
sftp = c.open_sftp()
OUT = ROOT / 'tmp_cam_diag'
for src, dst in [('/tmp/sw_front.jpg','switch_front.jpg'),('/tmp/sw_rear.jpg','switch_rear.jpg')]:
    try:
        (OUT/dst).write_bytes(sftp.file(src,'rb').read()); print('saved', dst)
    except Exception as e:
        print('miss', e)
sftp.close(); c.close()
