#!/usr/bin/env python3
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)

for wrap in (30, 40, 50, 60):
    sftp = c.open_sftp()
    with sftp.file("/tmp/_w.sh", "w") as f:
        f.write(
            f"""#!/bin/bash
cat >/etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf <<EOF
[Service]
Environment=CAMERA_WRAP_X={wrap}
EOF
systemctl daemon-reload
systemctl kill -s SIGTERM ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f camera-stream-server.py || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo.*1600x1184' || true
sleep 1
systemctl start ha-kiosk-camera-stream.service
sleep 5
python3 - <<PY
import urllib.request, threading, time
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=10).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/w{wrap}.jpg','wb').write(data)
print('snap', {wrap}, len(data))
PY
"""
        )
    sftp.chmod("/tmp/_w.sh", 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(40)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_w.sh")
    buf = b""
    t = time.time() + 40
    while time.time() < t:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    print(buf.decode("utf-8", "replace")[-400:])
    sftp = c.open_sftp()
    try:
        data = sftp.file(f"/tmp/w{wrap}.jpg", "rb").read()
        (OUT / f"w{wrap}.jpg").write_bytes(data)
        print("saved", wrap, len(data))
    except Exception as e:
        print("miss", wrap, e)
    sftp.close()

# Leave at best guess 40
sftp = c.open_sftp()
with sftp.file("/tmp/_fin.sh", "w") as f:
    f.write(
        """#!/bin/bash
cat >/etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf <<'EOF'
[Service]
Environment=CAMERA_WRAP_X=40
EOF
systemctl daemon-reload
systemctl restart ha-kiosk-camera-stream.service || systemctl start ha-kiosk-camera-stream.service
"""
    )
sftp.chmod("/tmp/_fin.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(25)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_fin.sh")
time.sleep(3)
c.close()
print("left at WRAP=40")
