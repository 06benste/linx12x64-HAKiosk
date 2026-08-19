#!/usr/bin/env python3
"""Force redeploy look, bump stream res/quality, verify snaps."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-look2/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 644 /tmp/ha-look2/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
install -m 755 /tmp/ha-look2/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-look2/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service
# Confirm defaults in deployed script
grep -n 'CAMERA_STREAM_WIDTH\|CAMERA_STREAM_QUALITY\|960\|640' /opt/ha-kiosk/scripts/camera-stream-server.py | head -n 20
systemctl daemon-reload
systemctl restart ha-kiosk-camera-stream.service
# mqtt republishes and will open /stream.mjpg — wait for listen + first frames
for i in $(seq 1 20); do
  if curl -fsS --max-time 2 -o /dev/null http://127.0.0.1:17824/snapshot.jpg 2>/dev/null; then
    break
  fi
  sleep 1
done
sleep 2
# settle auto over a few frames
for i in 1 2 3 4 5 6; do
  curl -fsS --max-time 12 -o /tmp/graded.jpg http://127.0.0.1:17824/snapshot.jpg
  sleep 0.35
done
curl -fsS --max-time 15 -o /tmp/plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'
python3 <<'PY'
from PIL import Image, ImageStat
for name in ('plain', 'graded'):
    im = Image.open(f'/tmp/{name}.jpg').convert('RGB')
    st = ImageStat.Stat(im)
    print(name, im.size, 'mean', [round(x, 1) for x in st.mean], 'bytes', __import__('os').path.getsize(f'/tmp/{name}.jpg'))
PY
journalctl -u ha-kiosk-camera-stream -n 12 --no-pager
systemctl show ha-kiosk-camera-stream -p Environment --no-pager
ps aux | grep 'ffmpeg.*rawvideo' | grep -v grep || true
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Update unit env for better default stream
    unit = (ROOT / "scripts" / "ha-kiosk-camera-stream.service").read_text(encoding="utf-8")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-look2")
    except OSError:
        pass
    for name, src in (
        ("camera_preview.json", ROOT / "config" / "camera_preview.json"),
        ("camera_preview.py", ROOT / "scripts" / "camera_preview.py"),
        ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
        ("ha-kiosk-camera-stream.service", ROOT / "scripts" / "ha-kiosk-camera-stream.service"),
    ):
        data = src.read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(f"/tmp/ha-look2/{name}", "wb") as f:
            f.write(data)
        print("up", name, flush=True)
    with sftp.file("/tmp/deploy-look2.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-look2.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-look2.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    for name in ("graded.jpg", "plain.jpg"):
        try:
            data = sftp.file(f"/tmp/{name}", "rb").read()
            (OUT / name).write_bytes(data)
            print("saved", name, len(data), flush=True)
        except Exception as e:
            print("fail", name, e, flush=True)
    sftp.close()
    c.close()
    if code != 0:
        raise SystemExit(code)
    print("OK", flush=True)


if __name__ == "__main__":
    main()
