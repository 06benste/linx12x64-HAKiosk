#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys
import time
import urllib.request

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)

    # Ensure stream unit up and camera power on
    cmd = r"""
set -euxo pipefail
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
echo 1 > /opt/ha-kiosk/config/camera_power
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 30); do
  if ss -ltn | grep -q ':17824'; then echo ready; break; fi
  sleep 1
done
ss -ltn | grep 17824
# warm pipeline
curl -fsS --max-time 90 -o /tmp/stream_snap.jpg http://127.0.0.1:17824/snapshot.jpg
ls -la /tmp/stream_snap.jpg
python3 - <<'PY'
from PIL import Image, ImageDraw, ImageFont
import time
img = Image.open('/tmp/stream_snap.jpg')
print('size', img.size, 'mode', img.mode)
# Crop top-centre band where timecode should be
w,h = img.size
band = img.crop((w//4, 0, 3*w//4, max(40, h//8)))
band.save('/tmp/stream_tc_band.jpg', quality=90)
print('band', band.size)
PY
journalctl -u ha-kiosk-camera-stream.service -n 8 --no-pager
"""
    sftp = c.open_sftp()
    data = (ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
        f.write(data)
    with sftp.file("/tmp/deploy-tc2.sh", "w") as f:
        f.write(cmd.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-tc2.sh", 0o755)
    sftp.close()

    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-tc2.sh", timeout=150, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    if o.channel.recv_exit_status() != 0:
        raise SystemExit(1)

    out = ROOT / "logs"
    out.mkdir(parents=True, exist_ok=True)
    sftp = c.open_sftp()
    sftp.get("/tmp/stream_snap.jpg", str(out / "stream_timecode_check.jpg"))
    sftp.get("/tmp/stream_tc_band.jpg", str(out / "stream_timecode_band.jpg"))
    sftp.close()
    c.close()

    from PIL import Image

    img = Image.open(out / "stream_timecode_check.jpg")
    print(f"local snapshot {img.size}", flush=True)
    # Read the band image so the vision path can inspect if needed
    band = Image.open(out / "stream_timecode_band.jpg")
    print(f"local band {band.size}", flush=True)
    print("OK", flush=True)


if __name__ == "__main__":
    main()
