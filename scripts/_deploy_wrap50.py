#!/usr/bin/env python3
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
with sftp.file("/tmp/_wrap50.sh", "w") as f:
    f.write(
        r"""#!/bin/bash
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
mkdir -p /etc/systemd/system/ha-kiosk-camera-stream.service.d
cat >/etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf <<'EOF'
[Service]
Environment=CAMERA_WRAP_X=50
Environment=CAMERA_CROP_X=0
Environment=CAMERA_CROP_W=1584
EOF
systemctl daemon-reload
systemctl kill -s SIGTERM ha-kiosk-camera-stream.service || true
sleep 1
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
print('WRAP', m.WRAP_X)
fg, cx = m.build_stream_filtergraph(m.load_look())
print('complex', cx, fg[:160])
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=12).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=25).read()
open('/tmp/wrap50.jpg','wb').write(data)
print('snap', len(data), list(data[:3]))
PY
"""
    )
sftp.chmod("/tmp/_wrap50.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(55)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_wrap50.sh")
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
print(buf.decode("utf-8", "replace")[-2500:])
sftp = c.open_sftp()
data = sftp.file("/tmp/wrap50.jpg", "rb").read()
sftp.close()
c.close()
(OUT / "wrap50_final.jpg").write_bytes(data)
print("saved", len(data))
