#!/usr/bin/env python3
"""Deploy restored look + softer auto; pull verification snaps."""
from __future__ import annotations

import pathlib
import shutil
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-look/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 644 /tmp/ha-look/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
install -m 755 /tmp/ha-look/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
systemctl restart ha-kiosk-camera-stream.service
# Wake stream (needs a client) and let auto settle a few frames
for i in 1 2 3 4 5; do
  curl -fsS --max-time 8 -o /tmp/graded.jpg http://127.0.0.1:17824/snapshot.jpg || true
  sleep 0.4
done
curl -fsS --max-time 20 -o /tmp/plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'
python3 - <<'PY'
from PIL import Image, ImageStat
for name in ('plain', 'graded'):
    im = Image.open(f'/tmp/{name}.jpg').convert('RGB')
    st = ImageStat.Stat(im)
    print(name, im.size, 'mean', [round(x, 1) for x in st.mean])
PY
journalctl -u ha-kiosk-camera-stream -n 10 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    shutil.copyfile(ROOT / "scripts" / "camera_preview.py", ROOT / "tools" / "camera_preview.py")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-look")
    except OSError:
        pass
    for name, src in (
        ("camera_preview.json", ROOT / "config" / "camera_preview.json"),
        ("camera_preview.py", ROOT / "scripts" / "camera_preview.py"),
        ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
    ):
        data = src.read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(f"/tmp/ha-look/{name}", "wb") as f:
            f.write(data)
        print("uploaded", name, flush=True)
    with sftp.file("/tmp/deploy-look.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-look.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-look.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    if o.channel.recv_exit_status() != 0:
        raise SystemExit(1)
    sftp = c.open_sftp()
    for name in ("graded.jpg", "plain.jpg"):
        data = sftp.file(f"/tmp/{name}", "rb").read()
        (OUT / name).write_bytes(data)
        print("saved", OUT / name, len(data), flush=True)
    sftp.close()
    c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
