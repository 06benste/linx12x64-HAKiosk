#!/usr/bin/env python3
"""Try WRAP_X candidates via env without rewriting defaults each time."""
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

# Ensure latest server is installed once
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
    f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
sftp.close()


def run(script, timeout=50):
    sftp = c.open_sftp()
    with sftp.file("/tmp/_job.sh", "w") as f:
        f.write("#!/bin/bash\n" + script + "\n")
    sftp.chmod("/tmp/_job.sh", 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(timeout)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_job.sh")
    buf = b""
    t = time.time() + timeout
    while time.time() < t:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    return buf.decode("utf-8", "replace")


print(
    run(
        "install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py; "
        # drop-in override for CAMERA_WRAP_X
        "mkdir -p /etc/systemd/system/ha-kiosk-camera-stream.service.d; "
        "true"
    )
)

for wrap in (80, 96, 112, 128, 144):
    print(f"\n=== WRAP {wrap} ===")
    print(
        run(
            f"""
mkdir -p /etc/systemd/system/ha-kiosk-camera-stream.service.d
cat >/etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf <<EOF
[Service]
Environment=CAMERA_WRAP_X={wrap}
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
sleep 5
python3 - <<PY
import urllib.request, threading, time, os
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=10).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/wrap_{wrap}.jpg','wb').write(data)
print('snap', len(data))
PY
""",
            timeout=45,
        )[-800:]
    )
    sftp = c.open_sftp()
    try:
        data = sftp.file(f"/tmp/wrap_{wrap}.jpg", "rb").read()
        (OUT / f"wrap_{wrap}.jpg").write_bytes(data)
        print("saved", wrap, len(data))
    except Exception as e:
        print("miss", wrap, e)
    sftp.close()

c.close()
print("DONE")
