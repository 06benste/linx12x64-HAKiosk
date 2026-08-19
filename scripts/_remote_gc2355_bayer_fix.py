#!/usr/bin/env python3
"""Apply Bayer/gain patch, rebuild DKMS, reboot, capture a clean JPEG."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "logs"

REMOTE = r"""
set -euxo pipefail
K=$(uname -r)
VER=1.0.3-linx
SRC=/usr/src/atomisp-6.10-${VER}
python3 /tmp/_patch_gc2355_bayer_gain.py
grep -nE 'bayer_order|SGRBG|SBGGR|0xb6, 0x00|0xb2, 0x40' \
  "$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c" \
  "$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h" | head -n 20
dkms remove atomisp-6.10/${VER} -k "$K" || true
dkms add "$SRC" || true
dkms build -m atomisp-6.10 -v "$VER" -k "$K"
dkms install -m atomisp-6.10 -v "$VER" -k "$K" --force
echo BUILD_OK
"""

POST = r"""
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 3
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
rm -f /tmp/cam.raw /tmp/cam_ok.jpg
timeout -s KILL 20 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
# Native geometry from driver: 1584x1184, bpl 1600
ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1184 -i /tmp/cam.raw \
  -vf crop=1584:1184:0:0 -frames:v 1 -update 1 /tmp/cam_ok.jpg 2>&1 | tail -n 8
ls -la /tmp/cam_ok.jpg
file /tmp/cam_ok.jpg
"""


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    return c


def run(c, cmd: str, title: str, timeout: int = 3600) -> int:
    print(f"=== {title} ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash -lc {repr(cmd)}",
        timeout=timeout,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    return stdout.channel.recv_exit_status()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = ssh()
    sftp = c.open_sftp()
    for name in ["_patch_gc2355_bayer_gain.py"]:
        text = (HERE / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        with sftp.file(f"/tmp/{name}", "w") as f:
            f.write(text)
    with sftp.file("/tmp/_rebuild_bayer.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/_rebuild_bayer.sh", 0o755)
    sftp.close()

    if run(c, "bash /tmp/_rebuild_bayer.sh", "dkms rebuild") != 0:
        raise SystemExit(1)

    print("=== reboot ===", flush=True)
    try:
        c.exec_command(f"echo {PASS} | sudo -S -p '' reboot", timeout=10)
    except Exception:
        pass
    c.close()
    time.sleep(25)
    for i in range(60):
        try:
            c = ssh()
            _, o, _ = c.exec_command("uptime", timeout=10)
            print("up:", o.read().decode().strip(), flush=True)
            break
        except Exception as e:
            print("wait", i, e, flush=True)
            time.sleep(5)
    else:
        raise SystemExit("no boot")

    time.sleep(18)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_post_bayer.sh", "w") as f:
        f.write(POST.replace("\r\n", "\n"))
    sftp.chmod("/tmp/_post_bayer.sh", 0o755)
    sftp.close()
    rc = run(c, "bash /tmp/_post_bayer.sh", "capture", timeout=180)
    sftp = c.open_sftp()
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        sftp.get("/tmp/cam_ok.jpg", str(OUT / "cam_ok.jpg"))
        print("downloaded cam_ok.jpg", (OUT / "cam_ok.jpg").stat().st_size, flush=True)
    except Exception as e:
        print("download failed", e, flush=True)
    sftp.close()
    c.close()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
