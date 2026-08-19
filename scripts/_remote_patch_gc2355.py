#!/usr/bin/env python3
"""Upload GC2355 table patch, rebuild atomisp-gc2235, reboot, capture."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
HERE = pathlib.Path(__file__).resolve().parent

REMOTE_SH = r"""
set -euxo pipefail
python3 /tmp/patch_gc2355_tables.py
SRC=/usr/src/atomisp-6.10-1.0.3-linx
K=$(uname -r)
KDIR=/lib/modules/$K/build
cd "$SRC"
touch atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c
echo "=== rebuild (long on Atom) ==="
make -C "$KDIR" M="$SRC" -j2
MODDIR=/lib/modules/$K/updates/dkms
install -m644 atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.ko "$MODDIR/atomisp-gc2235.ko"
# Prefer compressed like dkms
if command -v xz >/dev/null; then
  xz -f "$MODDIR/atomisp-gc2235.ko"
fi
depmod -a
echo REBUILD_OK
"""


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    return c


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = ssh()
    sftp = c.open_sftp()
    patch = (HERE / "_patch_gc2355_tables.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    with sftp.file("/tmp/patch_gc2355_tables.py", "w") as f:
        f.write(patch)
    with sftp.file("/tmp/rebuild_gc2355.sh", "w") as f:
        f.write(REMOTE_SH.replace("\r\n", "\n"))
    sftp.chmod("/tmp/rebuild_gc2355.sh", 0o755)
    sftp.close()

    print("=== patch + rebuild ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/rebuild_gc2355.sh",
        timeout=3600,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    code = stdout.channel.recv_exit_status()
    if code != 0:
        raise SystemExit(code)

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
            _, o, _ = c.exec_command("uptime; test -e /dev/video0 && echo VID || echo NOVID", timeout=15)
            out = o.read().decode()
            print(f"ping {i}: {out.strip()}", flush=True)
            if "VID" in out or "NOVID" in out:
                # give atomisp service time
                time.sleep(12)
                break
            c.close()
        except Exception as e:
            print(f"ping {i}: down ({e})", flush=True)
            time.sleep(5)
    else:
        raise SystemExit("no reboot")

    post = r"""
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 2
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
dmesg | grep -iE 'detect gc|stream|shisp|timeout|CSS|gc2235' | tail -n 30
media-ctl -d /dev/media0 -p 2>&1 | head -n 40 || true
v4l2-ctl -d /dev/video0 --list-formats-ext 2>&1 | head -n 40 || true
rm -f /tmp/cam.raw /tmp/camtest.jpg
timeout -s KILL 20 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=2 --stream-to=/tmp/cam.raw 2>&1 || true
ls -la /tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
if [[ "$SZ" -gt 100000 ]]; then
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1200 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 8
  ls -la /tmp/camtest.jpg
fi
dmesg | grep -iE 'timeout|CSS|FPS|error|fail' | tail -n 20
echo POST_OK
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-post2.sh", "w") as f:
        f.write(post.replace("\r\n", "\n"))
    sftp.chmod("/tmp/cam-post2.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/cam-post2.sh",
        timeout=180,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    code = stdout.channel.recv_exit_status()
    try:
        sftp = c.open_sftp()
        sftp.get("/tmp/camtest.jpg", str(HERE.parent / "logs" / "camtest.jpg"))
        print("saved logs/camtest.jpg", flush=True)
        sftp.close()
    except Exception as e:
        print("no image:", e, flush=True)
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
