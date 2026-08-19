#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
K=$(uname -r)
echo "kernel=$K"
echo '=== i2c names ==='
for d in /sys/bus/i2c/devices/*; do
  [ -f "$d/name" ] || continue
  printf '%s %s\n' "$(basename "$d")" "$(cat "$d/name")"
done
echo '=== pci ==='
lspci -nnk
echo '=== config atomisp ==='
grep -E 'ATOMISP|INTEL_ATOMISP|MEDIA_SUPPORT' /boot/config-$K 2>/dev/null | head -n 30
echo '=== tools ==='
command -v ffmpeg || true
command -v convert || true
dpkg -l ffmpeg python3-pil v4l-utils 2>/dev/null | awk '/^ii/{print}'
echo '=== display for x11 fallback check ==='
echo "DISPLAY users:"; who || true
ls /tmp/.X11-unix 2>/dev/null || true
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam2.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/cam2.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command("bash /tmp/cam2.sh", timeout=40)
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print(err[:500])
    c.close()


if __name__ == "__main__":
    main()
