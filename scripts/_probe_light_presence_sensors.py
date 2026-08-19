#!/usr/bin/env python3
"""Probe Linx tablet for ambient light / proximity / presence sensors."""
from __future__ import annotations

import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"

REMOTE = r"""
set -uo pipefail
echo '======== IIO devices ========'
ls -la /sys/bus/iio/devices 2>/dev/null || echo '(none)'
for d in /sys/bus/iio/devices/iio:device*; do
  [[ -d "$d" ]] || continue
  echo "--- $d ---"
  cat "$d/name" 2>/dev/null || true
  ls "$d" 2>/dev/null | head -80
  for f in "$d"/in_illuminance* "$d"/in_intensity* "$d"/in_proximity* "$d"/in_accel* "$d"/in_anglvel*; do
    [[ -e "$f" ]] || continue
    echo "  $f = $(cat "$f" 2>/dev/null | tr '\n' ' ')"
  done
done

echo
echo '======== input devices ========'
ls -la /dev/input 2>/dev/null || true
cat /proc/bus/input/devices 2>/dev/null || true

echo
echo '======== HID / sysfs sensor hints ========'
find /sys -maxdepth 5 \( -iname '*als*' -o -iname '*illum*' -o -iname '*light*sensor*' -o -iname '*proxim*' -o -iname '*ambient*' \) 2>/dev/null | head -80 || true

echo
echo '======== ACPI / firmware nodes ========'
ls /sys/bus/acpi/devices 2>/dev/null | grep -iE 'ALS|PROX|LID|SENS|INT|GCT|MSFT' || true
find /sys/bus/acpi/devices -maxdepth 3 -iname '*als*' 2>/dev/null | head -40 || true

echo
echo '======== i2c / spi buses ========'
ls -la /sys/bus/i2c/devices 2>/dev/null || echo '(no i2c)'
for d in /sys/bus/i2c/devices/*; do
  [[ -d "$d" ]] || continue
  name=$(cat "$d/name" 2>/dev/null || echo '?')
  echo "$d -> $name"
done
ls /sys/class/spi_master 2>/dev/null || true

echo
echo '======== dmesg sensor lines ========'
dmesg -T 2>/dev/null | grep -iE 'als|illum|ambient|proxim|light.?sensor|apds|bh17|opt300|tsl25|cm32|stk3|vcnl|ltr5|hx90|sensor.?hub' | tail -60 || true
journalctl -k -b --no-pager 2>/dev/null | grep -iE 'als|illum|ambient|proxim|light.?sensor|apds|bh17|opt300|tsl25|cm32|stk3|vcnl|ltr5' | tail -40 || true

echo
echo '======== modules / hwdb ========'
lsmod | grep -iE 'hid|iio|als|industrialio|intel_hid|hid_sensor|soc_button' || true
find /lib/modules/$(uname -r) -iname '*als*' -o -iname '*hid-sensor*' -o -iname '*proxim*' 2>/dev/null | head -40 || true

echo
echo '======== camera as light proxy? ========'
ls -la /dev/video* 2>/dev/null || true
v4l2-ctl --list-devices 2>/dev/null || true

echo
echo '======== DMI / product ========'
cat /sys/class/dmi/id/product_name 2>/dev/null; cat /sys/class/dmi/id/board_name 2>/dev/null; cat /sys/class/dmi/id/bios_version 2>/dev/null
uname -a
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/probe-sensors.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/probe-sensors.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/probe-sensors.sh",
        timeout=90,
        get_pty=True,
    )
    print(o.read().decode("utf-8", "replace"))
    c.close()


if __name__ == "__main__":
    main()
