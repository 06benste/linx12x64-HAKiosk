#!/usr/bin/env python3
"""Hot-deploy crop offset without wedging ISP (no stop if possible — restart carefully)."""
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
    f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
with sftp.file("/tmp/_hot.sh", "w") as f:
    f.write(
        r"""#!/bin/bash
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
# Soft restart: kill only the python server; let systemd restart it.
# Do NOT pkill v4l mid-stream if avoidable — use systemctl with short timeout.
systemctl kill -s SIGTERM ha-kiosk-camera-stream.service || true
sleep 2
pkill -9 -f '/opt/ha-kiosk/scripts/camera-stream-server.py' || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo.*1600x1184' || true
sleep 1
systemctl reset-failed ha-kiosk-camera-stream.service || true
systemctl start ha-kiosk-camera-stream.service
sleep 6
curl -fsS --max-time 4 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo
python3 - <<'PY'
import urllib.request, threading, time, importlib.util
spec=importlib.util.spec_from_file_location('css','/opt/ha-kiosk/scripts/camera-stream-server.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('WRAP', m.WRAP_X, 'CROP', m.CROP_X, m.CROP_W)
print('FG', m.build_stream_filtergraph(m.load_look())[0][:180])
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=12).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=25).read()
open('/tmp/cropfix.jpg','wb').write(data)
print('snap', len(data), list(data[:3]))
PY
"""
    )
sftp.chmod("/tmp/_hot.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(55)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_hot.sh")
buf = b""
t = time.time() + 55
while time.time() < t:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode("utf-8", "replace")[-3000:])
sftp = c.open_sftp()
data = sftp.file("/tmp/cropfix.jpg", "rb").read()
sftp.close()
c.close()
(OUT / "after_roll160.jpg").write_bytes(data)
print("saved", len(data))
