#!/usr/bin/env python3
"""Fix AtomISP firmware path, reload modules, try a capture."""
from __future__ import annotations

import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"

REMOTE = r"""
set -euxo pipefail
# Firmware expected under intel/ipu/
mkdir -p /lib/firmware/intel/ipu
if [[ -f /lib/firmware/shisp_2401a0_v21.bin ]]; then
  ln -sfn /lib/firmware/shisp_2401a0_v21.bin /lib/firmware/intel/ipu/shisp_2401a0_v21.bin
fi
ls -la /lib/firmware/intel/ipu/shisp_2401a0_v21.bin

# Ensure dummy PM stays blacklisted
grep -n . /etc/modprobe.d/blacklist-atomisp.conf || true

# Reload in correct order: unload ISP, load platform+sensors, then ISP
modprobe -r atomisp_gc0310 2>/dev/null || true
modprobe -r atomisp_gc2235 2>/dev/null || true
modprobe -r atomisp 2>/dev/null || true
modprobe -r atomisp_gmin_platform 2>/dev/null || true
# hyphen vs underscore names
modprobe -r atomisp-gc0310 2>/dev/null || true
modprobe -r atomisp-gc2235 2>/dev/null || true
sleep 1

modprobe atomisp_gmin_platform
modprobe atomisp-gc2235
sleep 1
modprobe atomisp
sleep 3

echo '=== devices ==='
ls -la /dev/video* /dev/media* 2>&1 || true
lspci -nnk -s 00:03.0
echo '=== v4l2 ==='
v4l2-ctl --list-devices 2>&1 || true
v4l2-ctl -d /dev/video0 --all 2>&1 | head -n 80 || true
echo '=== dmesg cam ==='
dmesg | grep -iE 'atomisp|gc2235|gc2355|GCTI|shisp|firmware.*shisp|no camera|ISP' | tail -n 60

echo '=== capture try ==='
# Prefer MJPEG/YUYV frame grab
rm -f /tmp/camtest.jpg /tmp/camtest.raw /tmp/camtest.ppm
if command -v ffmpeg >/dev/null; then
  timeout 20 ffmpeg -y -f v4l2 -video_size 640x480 -i /dev/video0 -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 40 || true
elif command -v fswebcam >/dev/null; then
  timeout 20 fswebcam -d /dev/video0 -r 640x480 --jpeg 85 /tmp/camtest.jpg 2>&1 || true
else
  apt-get install -y -qq ffmpeg >/dev/null
  timeout 20 ffmpeg -y -f v4l2 -video_size 640x480 -i /dev/video0 -frames:v 1 /tmp/camtest.jpg 2>&1 | tail -n 40 || true
fi
ls -la /tmp/camtest.* 2>&1 || true
file /tmp/camtest.jpg 2>&1 || true
echo OK_CAPTURE
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        username="kioskuser",
        password=PASS,
        timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    with sftp.file("/tmp/fix-cam-fw.sh", "w") as f:
        # Avoid Python EOL-backslash issues: no trailing \ in this script
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-cam-fw.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/fix-cam-fw.sh",
        timeout=600,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    code = stdout.channel.recv_exit_status()
    print("exit", code, flush=True)
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
