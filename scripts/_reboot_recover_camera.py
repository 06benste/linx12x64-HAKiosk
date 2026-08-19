#!/usr/bin/env python3
"""Reboot tablet, wait until back, redeploy stream server, verify real frames."""
from __future__ import annotations

import pathlib
import socket
import sys
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def ssh_connect(timeout: float = 20) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=timeout, allow_agent=False, look_for_keys=False)
    return c


def wait_down(seconds: float = 90) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, 22), timeout=2):
                time.sleep(2)
                continue
        except OSError:
            print("host down", flush=True)
            return
    print("warn: host still up?", flush=True)


def wait_up(seconds: float = 300) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, 22), timeout=3):
                # give sshd a moment
                time.sleep(3)
                c = ssh_connect(timeout=10)
                c.close()
                print("host up", flush=True)
                return
        except Exception:
            time.sleep(3)
    raise SystemExit("tablet did not come back")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("issuing reboot…", flush=True)
    c = ssh_connect()
    sftp = c.open_sftp()
    with sftp.file("/tmp/do-reboot.sh", "w") as f:
        f.write(
            "#!/bin/bash\n"
            "pkill -9 -f capture-tablet-cam || true\n"
            "pkill -9 -f 'v4l2-ctl' || true\n"
            "systemctl reboot\n"
        )
    sftp.chmod("/tmp/do-reboot.sh", 0o755)
    sftp.close()
    try:
        c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/do-reboot.sh", timeout=10, get_pty=True)
    except Exception:
        pass
    try:
        c.close()
    except Exception:
        pass

    wait_down()
    print("waiting for boot…", flush=True)
    wait_up()
    time.sleep(20)  # atomisp + kiosk settle

    c = ssh_connect()
    sftp = c.open_sftp()
    data = (ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
        f.write(data)
    remote = r"""
set -euxo pipefail
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
echo 1 > /opt/ha-kiosk/config/camera_power
systemctl restart ha-kiosk-atomisp.service || /opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 2
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service
for i in $(seq 1 45); do
  if ss -ltn | grep -q ':17824'; then echo ready; break; fi
  sleep 1
done
# warm stream
timeout 20 curl -fsS http://127.0.0.1:17824/stream.mjpg -o /dev/null &
sleep 10
curl -fsS --max-time 45 -o /tmp/snap_ok.jpg http://127.0.0.1:17824/snapshot.jpg
curl -fsS --max-time 45 -o /tmp/snap_ok_plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'
python3 - <<'PY'
from PIL import Image
import statistics, os
for p in ('/tmp/snap_ok.jpg','/tmp/snap_ok_plain.jpg'):
    im=Image.open(p).convert('RGB')
    m=[sum(px)/3 for px in list(im.getdata())[::30]]
    print(p, 'mean', round(statistics.mean(m),1), 'stdev', round(statistics.pstdev(m),1),
          'max', round(max(m),1), 'bytes', os.path.getsize(p))
PY
dmesg | grep -iE 'LINX_STREAM|detect gc|no camera' | tail -20 || true
systemctl is-active ha-kiosk-camera-stream.service
"""
    with sftp.file("/tmp/post-reboot-cam.sh", "w") as f:
        f.write(remote.replace("\r\n", "\n"))
    sftp.chmod("/tmp/post-reboot-cam.sh", 0o755)
    sftp.close()

    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/post-reboot-cam.sh",
        timeout=180,
        get_pty=True,
    )
    print(o.read().decode("utf-8", "replace"))
    rc = o.channel.recv_exit_status()

    out = ROOT / "logs"
    out.mkdir(exist_ok=True)
    sftp = c.open_sftp()
    for name in ("snap_ok.jpg", "snap_ok_plain.jpg"):
        try:
            sftp.get(f"/tmp/{name}", str(out / name))
            print("got", name)
        except Exception as e:
            print("miss", name, e)
    sftp.close()
    c.close()
    if rc != 0:
        raise SystemExit(rc)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
