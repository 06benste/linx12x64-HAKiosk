#!/usr/bin/env python3
"""Patch GC2355 stream fixes, full DKMS rebuild, reboot, capture test."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
HERE = pathlib.Path(__file__).resolve().parent

REMOTE = r"""
set -euxo pipefail
K=$(uname -r)
VER=1.0.3-linx
SRC=/usr/src/atomisp-6.10-${VER}

python3 /tmp/_patch_gc2355_stream_fixes.py
grep -nE '0x15, 0x62|0xf8, 0x08|LINX_SINGLE|LINX_STREAM|0x10, 0x90' \
  "$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h" \
  "$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.c" | head -n 30

dkms remove atomisp-6.10/${VER} -k "$K" || true
dkms add "$SRC" || true
dkms build -m atomisp-6.10 -v "$VER" -k "$K"
dkms install -m atomisp-6.10 -v "$VER" -k "$K" --force
echo BUILD_OK
"""

POST = r"""
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 4
dmesg -C || true
echo '=== detect ==='
dmesg | grep -iE 'detect gc|GCTI|camera pdata|LINX_CSI|port' | tail -n 30 || true
# re-show since dmesg -C may have wiped boot; also from journal
journalctl -k -b --no-pager 2>/dev/null | grep -iE 'detect gc|GCTI2355|camera pdata' | tail -n 20 || true
ls -l /dev/video0
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
rm -f /tmp/cam.raw
timeout -s KILL 20 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
echo '=== readback / stream logs ==='
dmesg | grep -iE 'LINX_STREAM|write error|gc2235|timeout|FPS|CSS|Sensor' | tail -n 60
"""


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        username="kioskuser",
        password=PASS,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c, script: str, title: str, timeout: int = 3600) -> int:
    print(f"=== {title} ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash -lc {repr(script)}",
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
    patch = (HERE / "_patch_gc2355_stream_fixes.py").read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    )
    with sftp.file("/tmp/_patch_gc2355_stream_fixes.py", "w") as f:
        f.write(patch)
    with sftp.file("/tmp/_rebuild_stream_fixes.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/_rebuild_stream_fixes.sh", 0o755)
    sftp.close()

    rc = run(c, "bash /tmp/_rebuild_stream_fixes.sh", "dkms rebuild")
    if rc != 0:
        raise SystemExit(rc)

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
    with sftp.file("/tmp/_post_stream_test.sh", "w") as f:
        f.write(POST.replace("\r\n", "\n"))
    sftp.chmod("/tmp/_post_stream_test.sh", 0o755)
    sftp.close()
    rc = run(c, "bash /tmp/_post_stream_test.sh", "capture test", timeout=180)
    c.close()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
