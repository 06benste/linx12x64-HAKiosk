#!/usr/bin/env python3
import pathlib
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
OUT.mkdir(exist_ok=True)

SCRIPT = r"""
set -x
systemctl stop ha-kiosk-camera-stream.service || true
# nuke anything holding the camera
kill -9 62302 64344 2>/dev/null || true
pkill -9 -f v4l2-ctl || true
pkill -9 -f 'ffmpeg.*rawvideo' || true
pkill -9 -f camera-stream-server || true
sleep 1
ps aux | grep -E 'v4l2-ctl|camera-stream|ffmpeg' | grep -v grep || echo no_cam_procs
# recover ISP if needed
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 2
systemctl reset-failed ha-kiosk-camera-stream.service || true
systemctl start ha-kiosk-camera-stream.service
sleep 5
systemctl is-active ha-kiosk-camera-stream.service
curl -fsS --max-time 4 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo
# leave service running; take snap
python3 - <<'PY'
import urllib.request, threading, time
def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=15).read(8192)
    except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=30).read()
open('/tmp/cropfix.jpg','wb').write(data)
print('snap', len(data), list(data[:3]))
# confirm vf uses crop x=16
import importlib.util
spec=importlib.util.spec_from_file_location('css','/opt/ha-kiosk/scripts/camera-stream-server.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('CROP', m.CROP_X, m.CROP_W)
print('VF', m.build_stream_vf(m.load_look())[:120])
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_recover.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_recover.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(70)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_recover.sh")
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
print(buf.decode("utf-8", "replace")[-5000:])
sftp = c.open_sftp()
try:
    data = sftp.file("/tmp/cropfix.jpg", "rb").read()
    (OUT / "after_cropx16.jpg").write_bytes(data)
    print("saved", len(data))
except Exception as e:
    print("pull", e)
sftp.close()
c.close()
