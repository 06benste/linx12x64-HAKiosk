#!/usr/bin/env python3
"""Restore DKMS modules, reinstall patched gc2235 cleanly, reboot, capture."""
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

# Ensure patch still applied
python3 /tmp/patch_gc2355_tables.py || true
grep -n 'GC2355 system\|0x10, 0x90' "$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h" | head

# Full dkms reinstall restores properly compressed modules from last good build,
# then we rebuild ONLY gc2235 object and swap it in.
echo "=== dkms install restore ==="
dkms install -m atomisp-6.10 -v "$VER" -k "$K" --force || {
  # If force unsupported, remove+install
  dkms uninstall -m atomisp-6.10 -v "$VER" -k "$K" || true
  dkms install -m atomisp-6.10 -v "$VER" -k "$K"
}

# Rebuild just gc2235 against current tree (patched header)
KDIR=/lib/modules/$K/build
cd "$SRC"
# Clean only the sensor object
rm -f atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.o \
      atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.ko \
      atomisp/6.12/drivers/staging/media/atomisp/i2c/.atomisp-gc2235*.cmd \
      atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.mod*
make -C "$KDIR" M="$SRC" atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.ko -j2

# Prefer uncompressed .ko to avoid xz corruption issues
rm -f /lib/modules/$K/updates/dkms/atomisp-gc2235.ko /lib/modules/$K/updates/dkms/atomisp-gc2235.ko.xz
install -m644 atomisp/6.12/drivers/staging/media/atomisp/i2c/atomisp-gc2235.ko \
  /lib/modules/$K/updates/dkms/atomisp-gc2235.ko
modinfo /lib/modules/$K/updates/dkms/atomisp-gc2235.ko | head -n 20
depmod -a

# Quick load test before reboot
modprobe -r atomisp_gc2235 2>/dev/null || true
modprobe -r atomisp 2>/dev/null || true
modprobe -r atomisp_gmin_platform 2>/dev/null || true
sleep 1
modprobe atomisp_gmin_platform
modprobe atomisp
sleep 1
modprobe atomisp-gc2235
sleep 2
dmesg | grep -iE 'gc2235|GCTI|detect gc|Invalid|decompression' | tail -n 30
lsmod | grep gc2235 || true
echo FIX_OK
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
    with sftp.file("/tmp/fix-gc2355-mod.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-gc2355-mod.sh", 0o755)
    sftp.close()

    print("=== restore + fix module ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/fix-gc2355-mod.sh",
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
    for i in range(50):
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

    time.sleep(15)
    post = r"""
set -euxo pipefail
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 3
dmesg | grep -iE 'detect gc|gc2235|GCTI|decompression|no camera|CSS|timeout' | tail -n 40
lspci -nnk -s 00:03.0
ls -la /dev/video0 2>&1 || true
media-ctl -d /dev/media0 -p 2>&1 | head -n 50 || true
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
rm -f /tmp/cam.raw /tmp/camtest.jpg
timeout -s KILL 25 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=2 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
if [[ "$SZ" -gt 100000 ]]; then
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1200 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 10
  ls -la /tmp/camtest.jpg
fi
dmesg | grep -iE 'timeout|CSS|FPS' | tail -n 15
echo POST_OK
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-post3.sh", "w") as f:
        f.write(post.replace("\r\n", "\n"))
    sftp.chmod("/tmp/cam-post3.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/cam-post3.sh",
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
