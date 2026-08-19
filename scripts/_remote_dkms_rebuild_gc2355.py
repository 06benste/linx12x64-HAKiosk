#!/usr/bin/env python3
"""Full DKMS rebuild with GC2355-patched gc2235.h, then capture test."""
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

python3 /tmp/patch_gc2355_tables.py
grep -E 'GC2355 system|0x10, 0x90|gc2355_1600_1200' \
  "$SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h" | head -n 10

# Force rebuild from patched sources
dkms remove atomisp-6.10/${VER} -k "$K" || true
dkms add "$SRC" || true
echo "=== dkms build ==="
dkms build -m atomisp-6.10 -v "$VER" -k "$K"
dkms install -m atomisp-6.10 -v "$VER" -k "$K" --force

# Keep dummy PM blacklisted
cat > /etc/modprobe.d/blacklist-atomisp.conf <<'EOF'
blacklist intel_atomisp2_pm
EOF

modinfo atomisp-gc2235 | head -n 15
echo BUILD_OK
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
    with sftp.file("/tmp/dkms-rebuild-gc2355.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/dkms-rebuild-gc2355.sh", 0o755)
    sftp.close()

    print("=== full dkms rebuild ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/dkms-rebuild-gc2355.sh",
        timeout=3600,
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
echo '=== dmesg ==='
dmesg | grep -iE 'detect gc|gc2235|GCTI|decompression|no camera|CSS|timeout|shisp' | tail -n 50
echo '=== pci ==='
lspci -nnk -s 00:03.0
echo '=== media ==='
media-ctl -d /dev/media0 -p 2>&1 | head -n 55 || true
pkill -9 -f 'ffmpeg|v4l2-ctl' || true
rm -f /tmp/cam.raw /tmp/camtest.jpg
# Prefer sensor native size from formats list
v4l2-ctl -d /dev/video0 --list-formats-ext 2>&1 | head -n 30 || true
timeout -s KILL 25 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=2 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
if [[ "$SZ" -gt 100000 ]]; then
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1600x1200 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 10
  ls -la /tmp/camtest.jpg
  file /tmp/camtest.jpg
fi
dmesg | grep -iE 'timeout|CSS|FPS|Sensor' | tail -n 20
echo POST_OK
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-post4.sh", "w") as f:
        f.write(post.replace("\r\n", "\n"))
    sftp.chmod("/tmp/cam-post4.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/cam-post4.sh",
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
