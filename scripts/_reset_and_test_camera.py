#!/usr/bin/env python3
"""Hard-reset camera stream and check if real frames return."""
from __future__ import annotations

import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

REMOTE = r"""
set -euxo pipefail
systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'camera-stream-server.py' || true
pkill -9 -f 'ffmpeg.*mjpeg' || true
sleep 1
# reload atomisp if helper exists
if [[ -x /opt/ha-kiosk/scripts/load-atomisp.sh ]]; then
  /opt/ha-kiosk/scripts/load-atomisp.sh || true
fi
sleep 1
ls -la /dev/video0
v4l2-ctl -d /dev/video0 --all 2>&1 | head -40

# Still capture test (independent of stream service)
python3 /opt/ha-kiosk/scripts/capture-tablet-cam.py /tmp/still_test.jpg 2>&1 | tail -30 || true
ls -la /tmp/still_test.jpg 2>&1 || true
python3 - <<'PY'
from PIL import Image
import statistics, os
p='/tmp/still_test.jpg'
if os.path.exists(p):
    im=Image.open(p).convert('RGB')
    m=[sum(px)/3 for px in list(im.getdata())[::80]]
    print('still', im.size, 'mean', round(statistics.mean(m),1), 'max', round(max(m),1), 'bytes', os.path.getsize(p))
else:
    print('still missing')
PY

systemctl start ha-kiosk-camera-stream.service
for i in $(seq 1 40); do
  if ss -ltn | grep -q ':17824'; then break; fi
  sleep 1
done
# hold a client open briefly so pipeline starts, then snapshot after warm-up
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
# background stream client
timeout 25 curl -fsS --max-time 25 http://127.0.0.1:17824/stream.mjpg -o /dev/null &
sleep 12
ps -eo pid,cmd | awk '/v4l2-ctl --stream|ffmpeg.*mjpeg|camera-stream-server/ {print}'
curl -fsS --max-time 30 -o /tmp/snap_after.jpg http://127.0.0.1:17824/snapshot.jpg
curl -fsS --max-time 30 -o /tmp/snap_after_plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'
python3 - <<'PY'
from PIL import Image
import statistics, os
for p in ('/tmp/snap_after.jpg','/tmp/snap_after_plain.jpg'):
    im=Image.open(p).convert('RGB')
    m=[sum(px)/3 for px in list(im.getdata())[::40]]
    print(p, im.size, 'mean', round(statistics.mean(m),1), 'max', round(max(m),1), 'bytes', os.path.getsize(p))
PY
journalctl -u ha-kiosk-camera-stream.service -n 25 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/reset-cam.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/reset-cam.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/reset-cam.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    sftp = c.open_sftp()
    for name in ("still_test.jpg", "snap_after.jpg", "snap_after_plain.jpg"):
        try:
            sftp.get(f"/tmp/{name}", f"C:/Users/ben_s/Projects/linx-ha-kiosk/logs/{name}")
            print("got", name)
        except Exception as e:
            print("miss", name, e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
