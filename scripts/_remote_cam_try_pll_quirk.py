#!/usr/bin/env python3
"""Add Linx GCTI2355 CsiPort quirks + GC2235-style 19.2MHz PLL; rebuild; test."""
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

# 1) CsiPort quirks
python3 /tmp/_patch_gmin_linx_quirk.py

# 2) Re-copy pristine gc2235.h then apply GC2355 patch with GC2235 PLL
if [[ -f /usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h ]]; then
  cp -a /usr/src/atomisp-dkms-src/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h \
        $SRC/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h
fi
python3 /tmp/patch_gc2355_tables.py
# Force PLL to GC2235 AtomISP values (19.2MHz proven)
python3 - <<'PY'
from pathlib import Path
p = Path("/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h")
t = p.read_text()
t2 = t.replace("{ GC2235_8BIT, 0xf7, 0x19 },", "{ GC2235_8BIT, 0xf7, 0x15 },", 1)
t2 = t2.replace("{ GC2235_8BIT, 0xf8, 0x08 }, /* was 0x06 @24MHz; 19.2MHz scaled */",
                "{ GC2235_8BIT, 0xf8, 0x84 }, /* GC2235 AtomISP 19.2MHz PLL */", 1)
t2 = t2.replace("{ GC2235_8BIT, 0xf9, 0x0e },", "{ GC2235_8BIT, 0xf9, 0xfe },", 1)
# Also try stream 0x90 (Rockchip) as well as 0x94 — use 0x90
t2 = t2.replace("{ GC2235_8BIT, 0x10, 0x94}, /* GC2355 1-lane RAW10 stream on */",
                "{ GC2235_8BIT, 0x10, 0x90}, /* GC2355 stream on (Rockchip) */", 1)
p.write_text(t2)
print("PLL now:", [l for l in p.read_text().splitlines() if "0xf7," in l or "0xf8," in l or "0xf9," in l or "0x10, 0x90" in l or "0x10, 0x94" in l][:8])
PY

dkms remove atomisp-6.10/${VER} -k "$K" || true
dkms add "$SRC" || true
dkms build -m atomisp-6.10 -v "$VER" -k "$K"
dkms install -m atomisp-6.10 -v "$VER" -k "$K" --force
cat > /etc/modprobe.d/blacklist-atomisp.conf <<'EOF'
blacklist intel_atomisp2_pm
EOF
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
    for name in ("_patch_gc2355_tables.py", "_patch_gmin_linx_quirk.py"):
        body = (HERE / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        with sftp.file(f"/tmp/{name}", "w") as f:
            f.write(body)
        # also alias
        if name.startswith("_patch_gc"):
            with sftp.file("/tmp/patch_gc2355_tables.py", "w") as f:
                f.write(body)
    with sftp.file("/tmp/rebuild3.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/rebuild3.sh", 0o755)
    sftp.close()

    print("=== rebuild ===", flush=True)
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/rebuild3.sh",
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
            print("up", c.exec_command("uptime")[1].read().decode().strip(), flush=True)
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
dmesg | grep -iE 'LINX_CSI|CsiPort|detect gc|camera pdata|port 0 already|detected' | tail -n 40
media-ctl -d /dev/media0 -p 2>&1 | head -n 60
pkill -9 -f v4l2-ctl || true
rm -f /tmp/cam.raw /tmp/camtest.jpg
dmesg -C
timeout -s KILL 45 v4l2-ctl -d /dev/video0 \
  --set-fmt-video=width=1584,height=1184,pixelformat=NV12 \
  --stream-mmap=4 --stream-count=3 --stream-to=/tmp/cam.raw 2>&1 || true
SZ=$(stat -c%s /tmp/cam.raw 2>/dev/null || echo 0)
echo "raw=$SZ"
dmesg | tail -n 40
if [[ "$SZ" -gt 100000 ]]; then
  ffmpeg -y -f rawvideo -pix_fmt nv12 -s 1584x1184 -i /tmp/cam.raw -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 8
  ls -la /tmp/camtest.jpg
fi
echo POST_OK
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/post5.sh", "w") as f:
        f.write(post.replace("\r\n", "\n"))
    sftp.chmod("/tmp/post5.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/post5.sh",
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
