#!/usr/bin/env python3
"""Push a brighter software look and verify snapshot means."""
from __future__ import annotations

import json
import pathlib
import sys
import time

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

LOOK = {
    "exposure_ev": 2.25,
    "contrast": 0.90,
    "saturation": 0.98,
    "wb_r": 1.62,
    "wb_g": 0.72,
    "wb_b": 1.08,
    "shadows": 0.70,
    "highlights": 0.35,
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = ROOT / "config" / "camera_preview.json"
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["software_preview"] = LOOK
    data["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["notes"] = "Dark-room look v2 (EV~2.4 + strong shadow lift, less green)"
    # Soften auto so it doesn't fight the brighter base as hard after save
    auto = data.setdefault("auto", {})
    auto["enabled"] = False  # stream uses ffmpeg static look; auto was unused in hot path
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/camera_preview_bright.json", "wb") as f:
        f.write(cfg_path.read_bytes().replace(b"\r\n", b"\n"))
    sftp.close()

    remote = r"""
set -euxo pipefail
install -m 644 /tmp/camera_preview_bright.json /opt/ha-kiosk/config/camera_preview.json
# Prefer API reload if stream is up; else restart unit
if curl -fsS --max-time 3 http://127.0.0.1:17824/api/look >/dev/null; then
  python3 - <<'PY'
import json, urllib.request
look = json.load(open('/opt/ha-kiosk/config/camera_preview.json'))['software_preview']
body = json.dumps({'software_preview': look}).encode()
req = urllib.request.Request('http://127.0.0.1:17824/api/look', data=body, headers={'Content-Type':'application/json'}, method='POST')
print(urllib.request.urlopen(req, timeout=45).read().decode())
PY
else
  systemctl restart ha-kiosk-camera-stream.service
  sleep 4
fi
python3 - <<'PY'
import io, json, time, urllib.request, threading
from PIL import Image, ImageStat

def suck():
    try:
        urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(512)
    except Exception as e:
        print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/ha_bright.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
print('size', im.size, 'mean', [round(x,1) for x in st.mean], 'bytes', len(data))
print('look', json.loads(urllib.request.urlopen('http://127.0.0.1:17824/api/look', timeout=5).read())['software_preview'])
PY
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/bright_look.sh", "w") as f:
        f.write(remote.replace("\r\n", "\n"))
    sftp.chmod("/tmp/bright_look.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/bright_look.sh", timeout=120, get_pty=True)
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
