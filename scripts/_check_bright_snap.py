#!/usr/bin/env python3
import io
import json
import time
import urllib.request
import threading

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
OUT = __import__("pathlib").Path(__file__).resolve().parents[1] / "tmp_cam_diag"


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    remote = r"""
python3 - <<'PY'
import io, json, time, urllib.request, threading, subprocess
from PIL import Image, ImageStat

print('journal', subprocess.getoutput('journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager'))
print('---vf---')
# reconstruct what build would do
import importlib.util
spec = importlib.util.spec_from_file_location('css', '/opt/ha-kiosk/scripts/camera-stream-server.py')
# too heavy; just print look and health
look = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/api/look', timeout=5).read())['software_preview']
print('look', look)

def suck():
    try:
        urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=25).read(2048)
    except Exception as e:
        print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(6)
data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/ha_bright2.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
# centre-left face band approx
band = im.crop((0, 100, 280, 500))
bst = ImageStat.Stat(band)
print('mean', [round(x,1) for x in st.mean], 'faceband', [round(x,1) for x in bst.mean], 'bytes', len(data))
print('health', json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read()))
PY
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/check_bright.sh", "w") as f:
        f.write(remote)
    sftp.chmod("/tmp/check_bright.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/check_bright.sh", timeout=90, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    sftp = c.open_sftp()
    blob = sftp.file("/tmp/ha_bright2.jpg", "rb").read()
    (OUT / "graded.jpg").write_bytes(blob)
    print("saved", len(blob))
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
