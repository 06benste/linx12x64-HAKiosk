#!/usr/bin/env python3
import pathlib
import socket
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

# Upload latest server, then reboot
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
    f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(20)
chan.get_pty()
chan.exec_command(
    f"echo {PASS} | sudo -S -p '' bash -c "
    "'install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py; reboot'"
)
time.sleep(2)
try:
    c.close()
except Exception:
    pass
print("reboot issued, waiting...")
time.sleep(25)

for i in range(48):
    try:
        s = socket.create_connection((HOST, 22), timeout=3)
        s.close()
        time.sleep(3)
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
        _, o, _ = c.exec_command("uptime", timeout=10)
        print("up", o.read().decode().strip())
        c.close()
        print(f"ssh ready after ~{25 + i * 5}s")
        break
    except Exception as e:
        print(f"wait {i}: {type(e).__name__}")
        time.sleep(5)
else:
    raise SystemExit("tablet never came back")

time.sleep(10)
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_postboot.sh", "w") as f:
    f.write(
        r"""#!/bin/bash
grep -n 'CROP_X = \|low_light' /opt/ha-kiosk/scripts/camera-stream-server.py | head
systemctl start ha-kiosk-camera-stream.service || true
systemctl start ha-kiosk-mqtt.service || true
sleep 8
systemctl is-active ha-kiosk-camera-stream.service
curl -fsS --max-time 5 http://127.0.0.1:17824/health; echo
python3 - <<'PY'
import urllib.request, threading, time, importlib.util
spec=importlib.util.spec_from_file_location('css','/opt/ha-kiosk/scripts/camera-stream-server.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('CROP', m.CROP_X, m.CROP_W)
print('VF', m.build_stream_vf(m.load_look())[:160])
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=12).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=30).read()
open('/tmp/cropfix.jpg','wb').write(data)
print('snap', len(data), list(data[:3]))
PY
"""
    )
sftp.chmod("/tmp/_postboot.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(70)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_postboot.sh")
buf = b""
t = time.time() + 70
while time.time() < t:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode("utf-8", "replace")[-4000:])
sftp = c.open_sftp()
data = sftp.file("/tmp/cropfix.jpg", "rb").read()
sftp.close()
c.close()
(OUT / "after_cropx16.jpg").write_bytes(data)
print("saved", len(data))
