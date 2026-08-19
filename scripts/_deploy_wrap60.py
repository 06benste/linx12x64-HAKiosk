#!/usr/bin/env python3
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

# Update default in source to 60
src = ROOT / "scripts" / "camera-stream-server.py"
text = src.read_text(encoding="utf-8")
text2 = text.replace(
    'os.environ.get("CAMERA_WRAP_X", "40")',
    'os.environ.get("CAMERA_WRAP_X", "60")',
)
if text2 != text:
    src.write_text(text2, encoding="utf-8")

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
    f.write(src.read_bytes().replace(b"\r\n", b"\n"))
with sftp.file("/tmp/_go.sh", "w") as f:
    f.write(
        r"""#!/bin/bash
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
cat >/etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf <<'EOF'
[Service]
Environment=CAMERA_WRAP_X=60
EOF
systemctl daemon-reload
systemctl kill -s SIGTERM ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f camera-stream-server.py || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo.*1600x1184' || true
sleep 1
systemctl start ha-kiosk-camera-stream.service
sleep 6
python3 - <<'PY'
import urllib.request, threading, time
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=12).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=25).read()
open('/tmp/final_wrap.jpg','wb').write(data)
print('snap', len(data))
PY
"""
    )
sftp.chmod("/tmp/_go.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(50)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_go.sh")
buf = b""
t = time.time() + 50
while time.time() < t:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode("utf-8", "replace")[-1500:])
sftp = c.open_sftp()
(OUT / "final_wrap.jpg").write_bytes(sftp.file("/tmp/final_wrap.jpg", "rb").read())
sftp.close()
c.close()
print("done")
