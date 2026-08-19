#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo '=== iio devices ==='
ls -la /sys/bus/iio/devices/ 2>/dev/null || echo none
for d in /sys/bus/iio/devices/iio:device*; do
  [ -d "$d" ] || continue
  echo "--- $d ---"
  cat "$d/name" 2>/dev/null; echo
  ls "$d" 2>/dev/null | head -80
  for f in "$d"/in_illuminance* "$d"/in_intensity* "$d"/in_proximity*; do
    [ -e "$f" ] || continue
    printf '  %s=' "$(basename "$f")"
    cat "$f" 2>/dev/null; echo
  done
done
echo '=== hwmon light-ish ==='
for h in /sys/class/hwmon/hwmon*; do
  printf '%s ' "$(basename "$h")"
  cat "$h/name" 2>/dev/null; echo
  ls "$h" 2>/dev/null | grep -iE 'lux|light|illum|als|intensity' || true
done
echo '=== input devices ==='
for e in /sys/class/input/event*/device/name; do
  [ -f "$e" ] || continue
  printf '%s: %s\n' "$(echo "$e" | cut -d/ -f5)" "$(cat "$e")"
done
echo '=== i2c devices ==='
for d in /sys/bus/i2c/devices/*; do
  [ -f "$d/name" ] || continue
  printf '%s: %s\n' "$(basename "$d")" "$(cat "$d/name")"
done
echo '=== sys als/illum paths ==='
find /sys -iname '*als*' 2>/dev/null | head -50
find /sys -iname '*illum*' 2>/dev/null | head -40
find /sys -iname '*ambient*' 2>/dev/null | head -40
echo '=== ACPI HID interesting ==='
grep -rsl . /sys/bus/acpi/devices/*/hid 2>/dev/null | while read -r f; do
  hid=$(cat "$f")
  case "$hid" in
    *ALS*|*als*|INT33*|ACPI0008*|MSHW*|KIOX*|GCTI*|FTSC*) printf '%s %s\n' "$f" "$hid" ;;
  esac
done
echo '=== modules present ==='
K=$(uname -r)
find /lib/modules/"$K" -iname '*als*' -o -iname '*hid-sensor*' -o -iname '*opt300*' -o -iname '*ltr*' -o -iname '*apds*' -o -iname '*cm3*' -o -iname '*bh17*' -o -iname '*tsl*' 2>/dev/null | head -60
lsmod | grep -iE 'als|hid_sensor|iio|light|apds|cm3|ltr|tsl|bh17|opt300|industrialio' || true
echo '=== dmesg ==='
dmesg 2>/dev/null | grep -iE 'als|ambient|illum|light.?sensor|proximity|opt300|ltr|apds|iio' | tail -40
echo '=== sensors cmd ==='
command -v sensors && sensors 2>/dev/null | head -60
echo '=== ACPI tables light strings ==='
if command -v acpidump >/dev/null; then
  echo kiosk | sudo -S -p '' acpidump 2>/dev/null | strings | grep -iE 'ALS|ambient|ILLUM|OPT300|LTR|APDS' | head -40
elif [ -d /sys/firmware/acpi/tables ]; then
  for t in /sys/firmware/acpi/tables/*; do
    strings "$t" 2>/dev/null | grep -iE 'ALS|OPT300|LTR-|APDS|ambient light' && echo " in $t"
  done | head -40
fi
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/als-probe.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/als-probe.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command("bash /tmp/als-probe.sh", timeout=60)
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print(err[:800])
    c.close()


if __name__ == "__main__":
    main()
