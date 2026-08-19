#!/usr/bin/env python3
"""Deploy software auto 3A for camera stream."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-auto/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 644 /tmp/ha-auto/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
install -m 755 /tmp/ha-auto/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 30); do
  ss -ltn | grep -q ':17824' && break
  sleep 1
done
timeout 15 curl -fsS http://127.0.0.1:17824/stream.mjpg -o /dev/null &
sleep 8
curl -fsS --max-time 30 -o /tmp/auto_snap.jpg http://127.0.0.1:17824/snapshot.jpg
curl -fsS --max-time 30 -o /tmp/auto_plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'
python3 - <<'PY'
from PIL import Image
import statistics, os
for p in ('/tmp/auto_plain.jpg','/tmp/auto_snap.jpg'):
    im=Image.open(p).convert('RGB')
    m=[sum(px)/3 for px in list(im.getdata())[::25]]
    print(p, 'mean', round(statistics.mean(m),1), 'stdev', round(statistics.pstdev(m),1),
          'bytes', os.path.getsize(p))
PY
journalctl -u ha-kiosk-camera-stream.service -n 12 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-auto")
    except OSError:
        pass
    for name, path in {
        "camera_preview.json": ROOT / "config" / "camera_preview.json",
        "camera_preview.py": ROOT / "scripts" / "camera_preview.py",
        "camera-stream-server.py": ROOT / "scripts" / "camera-stream-server.py",
    }.items():
        with sftp.file(f"/tmp/ha-auto/{name}", "wb") as f:
            f.write(path.read_bytes().replace(b"\r\n", b"\n"))
        print("uploaded", name, flush=True)
    with sftp.file("/tmp/deploy-auto.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-auto.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-auto.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    if o.channel.recv_exit_status() != 0:
        raise SystemExit(1)
    out = ROOT / "logs"
    out.mkdir(exist_ok=True)
    sftp = c.open_sftp()
    for name in ("auto_snap.jpg", "auto_plain.jpg"):
        sftp.get(f"/tmp/{name}", str(out / name))
    sftp.close()
    c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
