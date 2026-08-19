#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo '=== DMI / BIOS ==='
for f in bios_vendor bios_version bios_date board_vendor board_name board_version product_name product_version sys_vendor; do
  printf '%-18s %s\n' "$f" "$(cat /sys/class/dmi/id/$f 2>/dev/null)"
done
echo
echo '=== efivars interesting ==='
ls /sys/firmware/efi/efivars 2>/dev/null | grep -iE 'USB|OTG|CHG|CHARGE|POWER|BAT|AXP|Boot|Secure' | head -40
echo
echo '=== axp288 extcon cable type ==='
for n in /sys/class/extcon/*; do
  echo "-- $n --"
  cat "$n/name" 2>/dev/null; echo
  cat "$n/state" 2>/dev/null; echo
done
echo
echo '=== charger + battery now ==='
P=/sys/class/power_supply/axp288_charger
B=/sys/class/power_supply/axp288_fuel_gauge
echo "icl=$(cat $P/input_current_limit) online=$(cat $P/online)"
echo "status=$(cat $B/status) cap=$(cat $B/capacity) I=$(cat $B/current_now) V=$(cat $B/voltage_now)"
echo
echo '=== kernel cmdline / sleep ==='
cat /proc/cmdline
systemctl is-enabled sleep.target suspend.target 2>&1
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/bios-probe.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/bios-probe.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/bios-probe.sh", timeout=30)
    print(stdout.read().decode())
    c.close()


if __name__ == "__main__":
    main()
