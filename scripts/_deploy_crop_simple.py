#!/usr/bin/env python3
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

SCRIPT = r"""
set -x
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
grep -n 'CROP_X\|CAMERA_CROP' /opt/ha-kiosk/scripts/camera-stream-server.py | head
systemctl restart ha-kiosk-camera-stream.service
sleep 8
systemctl is-active ha-kiosk-camera-stream.service || true
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager -o short-iso || true
curl -fsS --max-time 5 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo
python3 /tmp/dosnap.py
"""

SNAP = r'''
import urllib.request, threading, time
def suck():
    try:
        urllib.request.urlopen("http://127.0.0.1:17824/stream.mjpg", timeout=12).read(4096)
    except Exception as e:
        print("wake", e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
for i in range(6):
    try:
        data = urllib.request.urlopen("http://127.0.0.1:17824/snapshot.jpg", timeout=25).read()
        open("/tmp/cropfix.jpg", "wb").write(data)
        print("snap", len(data), list(data[:3]))
        break
    except Exception as e:
        print("try", i, e)
        time.sleep(2)
'''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
    f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
with sftp.file("/tmp/dosnap.py", "w") as f:
    f.write(SNAP)
with sftp.file("/tmp/_crop_deploy.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_crop_deploy.sh", 0o755)
sftp.close()

chan = c.get_transport().open_session()
chan.settimeout(90)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_crop_deploy.sh")
buf = b""
t = time.time() + 90
while time.time() < t:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
print(buf.decode("utf-8", "replace")[-6000:])

sftp = c.open_sftp()
try:
    data = sftp.file("/tmp/cropfix.jpg", "rb").read()
    (OUT / "after_cropx16.jpg").write_bytes(data)
    print("saved", len(data))
except Exception as e:
    print("pull", e)
sftp.close()
c.close()
