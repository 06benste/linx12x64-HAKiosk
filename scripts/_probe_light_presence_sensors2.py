#!/usr/bin/env python3
from __future__ import annotations
import sys
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
REMOTE = r"""
echo '=== ACPI ALS/prox IDs ==='
ls /sys/bus/acpi/devices | grep -iE 'ACPI0008|ACPI000B|PNP0C0[CD]|ALS|PROX' || echo none
echo '=== children on i2c buses ==='
for b in 0 1 2 3 4 5 6; do
  echo -n "i2c-$b: "
  ls /sys/bus/i2c/devices/i2c-$b/ 2>/dev/null | grep -E '^[0-9a-f]|:' | tr '\n' ' '
  echo
done
echo '=== HID sensor hub present? ==='
lsmod | grep hid_sensor || echo 'hid_sensor_* not loaded'
find /sys -name '*HID-SENSOR*' 2>/dev/null | head -20 || true
echo '=== backlight ==='
ls /sys/class/backlight 2>/dev/null
cat /sys/class/backlight/*/actual_brightness 2>/dev/null || true
"""

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/probe-sensors2.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/probe-sensors2.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/probe-sensors2.sh", timeout=60, get_pty=True)
    print(o.read().decode("utf-8", "replace")[-6000:])
    c.close()

if __name__ == "__main__":
    main()
