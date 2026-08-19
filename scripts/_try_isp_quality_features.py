#!/usr/bin/env python3
"""Find ISP firmware and try enabling AtomISP quality features."""
import io
import json
import pathlib
import time
import urllib.request
import threading

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

CMD = r"""
set -euxo pipefail
echo '=== find firmware ==='
find /lib/firmware /usr/lib/firmware /opt -iname '*shisp*' 2>/dev/null | head -40 || true
find /lib/firmware /usr/lib/firmware -iname '*2401*' 2>/dev/null | head -40 || true
modinfo atomisp 2>/dev/null | head -40 || true
echo '=== enable ISP helpers while stream down ==='
systemctl stop ha-kiosk-camera-stream.service
sleep 1
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 0.5
# Turn on noise / false-color helpers if accepted
for c in \
  'fixed_pattern_noise_reduction=1' \
  'false_color_correction=1' \
  'bad_pixel_correction=1' \
  'low_light_mode=1' \
  'gdc_cac=1'
do
  echo "SET $c"
  v4l2-ctl -d /dev/video0 -c "$c" 2>&1 || true
done
v4l2-ctl -d /dev/video0 -l 2>&1 | head -40 || true
systemctl start ha-kiosk-camera-stream.service
for i in $(seq 1 25); do
  curl -fsS --max-time 2 http://127.0.0.1:17824/health >/dev/null && break
  sleep 1
done
python3 - <<'PY'
import io, json, time, urllib.request, threading
from PIL import Image, ImageStat
def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(1024)
    except Exception as e: print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(5)
data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/ha_ispfeat.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
print('mean', [round(x,1) for x in st.mean], 'bytes', len(data))
print('look', json.loads(urllib.request.urlopen('http://127.0.0.1:17824/api/look').read())['software_preview'])
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/isp_feat.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/isp_feat.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/isp_feat.sh", timeout=120, get_pty=True)
print(o.read().decode("utf-8", "replace"))
sftp = c.open_sftp()
try:
    blob = sftp.file("/tmp/ha_ispfeat.jpg", "rb").read()
    (OUT / "graded_ispfeat.jpg").write_bytes(blob)
    print("saved", len(blob))
except Exception as e:
    print("snap missing", e)
sftp.close()
c.close()
