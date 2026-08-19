#!/usr/bin/env python3
"""Deploy stream server + look only (no kiosk session restart)."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

LOOK = {
    "exposure_ev": 2.15,
    "contrast": 0.92,
    "saturation": 1.00,
    "wb_r": 1.50,
    "wb_g": 0.88,
    "wb_b": 1.02,
    "shadows": 0.65,
    "highlights": 0.32,
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = ROOT / "config" / "camera_preview.json"
    import json

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["software_preview"] = LOOK
    data["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["notes"] = "Dark-room look v3 (EV~2.35 + shadow lift + highlight soft)"
    data.setdefault("auto", {})["enabled"] = False
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
        f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/cam-tuner.html", "wb") as f:
        f.write((ROOT / "scripts" / "static" / "cam-tuner.html").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/camera_preview_bright.json", "wb") as f:
        f.write(cfg_path.read_bytes().replace(b"\r\n", b"\n"))
    sftp.close()

    remote = r"""
set -euxo pipefail
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/cam-tuner.html /opt/ha-kiosk/scripts/static/cam-tuner.html
install -m 644 /tmp/camera_preview_bright.json /opt/ha-kiosk/config/camera_preview.json
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:17824/health >/dev/null; then break; fi
  sleep 1
done
python3 - <<'PY'
import io, json, time, urllib.request, threading
from PIL import Image, ImageStat

def suck():
    try:
        urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(512)
    except Exception as e:
        print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/ha_bright.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
print('size', im.size, 'mean', [round(x,1) for x in st.mean], 'bytes', len(data))
print('look', json.loads(urllib.request.urlopen('http://127.0.0.1:17824/api/look', timeout=5).read())['software_preview'])
print('health', json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read()))
PY
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/deploy_bright.sh", "w") as f:
        f.write(remote.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy_bright.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy_bright.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    try:
        blob = sftp.file("/tmp/ha_bright.jpg", "rb").read()
        (OUT / "graded.jpg").write_bytes(blob)
        print("saved", OUT / "graded.jpg", len(blob))
    except Exception as e:
        print("snap missing", e)
    sftp.close()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
