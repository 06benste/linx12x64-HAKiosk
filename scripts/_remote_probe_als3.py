#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo kiosk | sudo -S -p '' modprobe i2c-dev
ls -la /dev/i2c-* 2>&1
echo '=== all ACPI devices with path ==='
for d in /sys/bus/acpi/devices/*; do
  [ -f "$d/path" ] || continue
  printf '%-20s %-8s %s\n' "$(basename "$d")" "$(cat "$d/status" 2>/dev/null)" "$(cat "$d/path" 2>/dev/null)"
done | sort
echo '=== i2c buses after i2c-dev ==='
for b in /dev/i2c-*; do
  n=${b#/dev/i2c-}
  echo "-- bus $n --"
  echo kiosk | sudo -S -p '' i2cdetect -y "$n" 2>&1 | head -18
done
echo '=== DSDT dump for ALS-ish ==='
TMP=/tmp/dsdt.dat
echo kiosk | sudo -S -p '' cat /sys/firmware/acpi/tables/DSDT > "$TMP"
strings "$TMP" | grep -E 'ALS|ALSD|ALSL|ILLUM|LUX|OPT3|LTR5|APDS|CM32|BH17|TSL2|AMBI|Light' | head -50
echo '--- device-like tokens ---'
strings "$TMP" | grep -E '^[_A-Z]{3,4}0?$' | sort -u | grep -iE 'AL|LUX|SEN|OPT|LTR|PRX|PS' | head -40
# Try iasl if present
if command -v iasl >/dev/null; then
  iasl -d "$TMP" 2>/dev/null
  grep -n -iE 'ALS|ambient|illumin|ACPI0008|light sensor' /tmp/dsdt.dsl | head -40
fi
echo '=== INT33D3 / INT339A ==='
for id in INT33D3 INT339A INT33A2 INT33A4 INT33BD INT33D5 INT33F5 INT33FD; do
  for d in /sys/bus/acpi/devices/${id}:*; do
    [ -d "$d" ] || continue
    printf '%s path=%s status=%s\n' "$(basename "$d")" "$(cat "$d/path")" "$(cat "$d/status")"
    ls "$d" 2>/dev/null | head
  done
done
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/als3.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/als3.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command("bash /tmp/als3.sh", timeout=90)
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err:
        print("STDERR:", err[:1000])
    c.close()


if __name__ == "__main__":
    main()
