#!/usr/bin/env python3
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)


def run(c, script, timeout=60):
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


c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)

# ensure script installed
sftp = c.open_sftp()
with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
    f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
sftp.close()
print(
    run(
        c,
        """
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f camera-stream-server || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo' || true
sleep 1
systemctl start ha-kiosk-camera-stream.service
sleep 6
systemctl is-active ha-kiosk-camera-stream.service
ss -ltn | grep 17824 || true
curl -fsS --max-time 4 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo
journalctl -u ha-kiosk-camera-stream.service -n 25 --no-pager -o short-iso | tail -25
""",
        timeout=50,
    )
)

print(
    run(
        c,
        """
python3 - <<'PY'
import urllib.request, threading, time
def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=12).read(4096)
    except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=25).read()
open('/tmp/cropfix.jpg','wb').write(data)
print('snap', len(data), list(data[:3]))
PY
""",
        timeout=45,
    )
)

sftp = c.open_sftp()
data = sftp.file("/tmp/cropfix.jpg", "rb").read()
sftp.close()
c.close()
(OUT / "after_cropx16.jpg").write_bytes(data)
print("saved", len(data))
