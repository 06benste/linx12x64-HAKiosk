#!/usr/bin/env python3
"""Deploy MJPEG camera stream service + update MQTT bridge."""
from __future__ import annotations

import pathlib
import sys
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
command -v ffmpeg >/dev/null
command -v v4l2-ctl >/dev/null
python3 -c 'from PIL import Image' >/dev/null

install -d -m 755 /opt/ha-kiosk/config /opt/ha-kiosk/scripts
install -m 644 /tmp/ha-stream/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 755 /tmp/ha-stream/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-stream/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
install -m 755 /tmp/ha-stream/capture-tablet-cam.py /opt/ha-kiosk/scripts/capture-tablet-cam.py
install -m 755 /tmp/ha-stream/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
install -m 644 /tmp/ha-stream/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service

systemctl daemon-reload
systemctl enable ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service
sleep 3
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager

# Warm snapshot (starts pipeline)
curl -fsS --max-time 45 -o /tmp/stream_snap.jpg http://127.0.0.1:17824/snapshot.jpg || true
ls -la /tmp/stream_snap.jpg || true
file /tmp/stream_snap.jpg || true
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
journalctl -u ha-kiosk-camera-stream.service -n 30 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-stream")
    except OSError:
        pass
    files = {
        "camera_preview.json": ROOT / "config" / "camera_preview.json",
        "camera-stream-server.py": ROOT / "scripts" / "camera-stream-server.py",
        "camera_preview.py": ROOT / "scripts" / "camera_preview.py",
        "capture-tablet-cam.py": ROOT / "scripts" / "capture-tablet-cam.py",
        "ha-kiosk-mqtt.py": ROOT / "scripts" / "ha-kiosk-mqtt.py",
        "ha-kiosk-camera-stream.service": ROOT / "scripts" / "ha-kiosk-camera-stream.service",
    }
    for name, path in files.items():
        with sftp.file(f"/tmp/ha-stream/{name}", "wb") as f:
            f.write(path.read_bytes().replace(b"\r\n", b"\n"))
        print("uploaded", name, flush=True)
    with sftp.file("/tmp/deploy-stream.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-stream.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-stream.sh",
        timeout=180,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    if stdout.channel.recv_exit_status() != 0:
        raise SystemExit(1)

    # Verify from PC
    print("=== LAN snapshot/stream check ===", flush=True)
    time.sleep(1)
    try:
        with urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=5) as r:
            print("health", r.read().decode()[:300], flush=True)
        with urllib.request.urlopen(f"http://{HOST}:17824/snapshot.jpg", timeout=30) as r:
            data = r.read()
            out = ROOT / "logs" / "stream_snapshot.jpg"
            out.write_bytes(data)
            print(f"snapshot {len(data)} bytes -> {out}", flush=True)
        # Pull a couple seconds of MJPEG
        req = urllib.request.urlopen(f"http://{HOST}:17824/stream.mjpg", timeout=20)
        buf = b""
        start = time.time()
        while time.time() - start < 4:
            buf += req.read(8192)
            if buf.count(b"\xff\xd8") >= 3:
                break
        req.close()
        markers = buf.count(b"\xff\xd8")
        print(f"stream bytes_sampled={len(buf)} jpeg_markers={markers}", flush=True)
    except Exception as exc:
        print("LAN verify failed:", exc, flush=True)
        raise SystemExit(1)
    finally:
        c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
