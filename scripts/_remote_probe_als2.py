#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo '=== GCTI2355 ==='
for d in /sys/bus/acpi/devices/GCTI2355:*; do
  echo "DIR $d"
  ls -la "$d" 2>/dev/null
  for f in path status hid uid adr modalias uevent power_state; do
    [ -f "$d/$f" ] && printf '  %s=%s\n' "$f" "$(cat "$d/$f" 2>/dev/null)"
  done
  # physical node?
  ls -la "$d/physical_node" 2>/dev/null || true
  find "$d" -maxdepth 3 -type f 2>/dev/null | head -40
done
echo '=== INT33FE/FF ==='
for d in /sys/bus/acpi/devices/INT33FE:* /sys/bus/acpi/devices/INT33FF:*; do
  [ -d "$d" ] || continue
  printf '%s path=%s status=%s\n' "$(basename "$d")" "$(cat "$d/path" 2>/dev/null)" "$(cat "$d/status" 2>/dev/null)"
done
echo '=== try acpi-als ==='
echo kiosk | sudo -S -p '' modprobe acpi_als 2>&1
echo kiosk | sudo -S -p '' modprobe hid_sensor_als 2>&1
ls /sys/bus/iio/devices/ 2>/dev/null
echo '=== ACPI0008 / ALS in tables ==='
echo kiosk | sudo -S -p '' bash -c 'for t in /sys/firmware/acpi/tables/*; do
  s=$(strings "$t" 2>/dev/null)
  echo "$s" | grep -qiE "ACPI0008|ALS0|ALSD|ambient|ILLUMIN|OPT300|LTR[_-]|APDS|CM32|BH17|TSL|light sensor|ALS " && {
    echo "=== $(basename $t) ==="
    echo "$s" | grep -iE "ACPI0008|ALS0|ALSD|ambient|ILLUMIN|OPT300|LTR|APDS|CM32|BH17|TSL|ALS" | head -30
  }
done'
echo '=== i2c detect buses 0-6 ==='
command -v i2cdetect || (echo kiosk | sudo -S -p '' apt-get install -y -qq i2c-tools >/dev/null)
for b in 0 1 2 3 4 5 6; do
  echo "-- bus $b --"
  echo kiosk | sudo -S -p '' i2cdetect -y $b 2>&1 | head -20
done
echo '=== backlight ==='
ls -la /sys/class/backlight/*/ 2>/dev/null | head -40
for b in /sys/class/backlight/*; do
  echo "BACKLIGHT $b"
  for f in brightness actual_brightness max_brightness type; do
    [ -f "$b/$f" ] && printf '  %s=%s\n' "$f" "$(cat "$b/$f")"
  done
done
echo '=== accel readings (sanity) ==='
d=/sys/bus/iio/devices/iio:device0
echo name=$(cat $d/name)
echo x=$(cat $d/in_accel_x_raw) y=$(cat $d/in_accel_y_raw) z=$(cat $d/in_accel_z_raw) scale=$(cat $d/in_accel_scale)
echo '=== dmi ==='
cat /sys/class/dmi/id/product_name /sys/class/dmi/id/board_name /sys/class/dmi/id/bios_version 2>/dev/null
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/als2.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/als2.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/als2.sh", timeout=120
    )
    print(stdout.read().decode())
    err = stderr.read().decode()
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1500:])
    c.close()


if __name__ == "__main__":
    main()
