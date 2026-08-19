#!/usr/bin/env python3
"""Quick look tweak via API + snapshot."""
from __future__ import annotations

import io
import json
import pathlib
import time

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"

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
    cfg = ROOT / "config" / "camera_preview.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["software_preview"] = LOOK
    data["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["notes"] = "Dark-room look v4 (brighter + teal cut + shadow curves)"
    cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/camera_preview_bright.json", "wb") as f:
        f.write(cfg.read_bytes().replace(b"\r\n", b"\n"))
    sftp.close()
    remote = r"""
set -euxo pipefail
install -m 644 /tmp/camera_preview_bright.json /opt/ha-kiosk/config/camera_preview.json
python3 - <<'PY'
import io, json, time, urllib.request, threading
from PIL import Image, ImageStat
look = json.load(open('/opt/ha-kiosk/config/camera_preview.json'))['software_preview']
body = json.dumps({'software_preview': look}).encode()
req = urllib.request.Request('http://127.0.0.1:17824/api/look', data=body, headers={'Content-Type':'application/json'}, method='POST')
print(urllib.request.urlopen(req, timeout=45).read().decode())
def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(1024)
    except Exception as e: print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(5)
data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/ha_bright.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
band = im.crop((180, 80, 520, 480))
bst = ImageStat.Stat(band)
print('mean', [round(x,1) for x in st.mean], 'face', [round(x,1) for x in bst.mean])
PY
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/tweak_look.sh", "w") as f:
        f.write(remote)
    sftp.chmod("/tmp/tweak_look.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/tweak_look.sh", timeout=90, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    sftp = c.open_sftp()
    (OUT / "graded.jpg").write_bytes(sftp.file("/tmp/ha_bright.jpg", "rb").read())
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
