#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
PHYS=$(readlink -f /sys/bus/i2c/devices/i2c-INT33F4:00)
echo PHYS=$PHYS
BUSNO=$(echo "$PHYS" | sed -n 's#.*/i2c-\([0-9]\+\)/.*#\1#p' | head -1)
echo BUSNO=$BUSNO
ADDR=0x34
if [ -n "$BUSNO" ]; then
  echo '=== selected regs ==='
  for reg in 0x00 0x01 0x02 0x10 0x30 0x31 0x32 0x33 0x34 0x35 0x36 0x40; do
    printf 'reg %s = ' "$reg"
    i2cget -y -f "$BUSNO" "$ADDR" "$reg" 2>&1
  done
  echo '=== dump ==='
  i2cdump -y -f "$BUSNO" "$ADDR" b 2>&1 | head -18
fi
# From axp288_charger.c: CHRG_CCBC etc — try enabling via power_supply STATUS write? usually RO
ls /sys/class/power_supply/axp288_charger/
# Re-trigger: write online? no
# Watch if ICL write changes reg 0x35/0x36 (input current often)
P=/sys/class/power_supply/axp288_charger/input_current_limit
echo before_reg35=$(i2cget -y -f "$BUSNO" "$ADDR" 0x35 2>/dev/null)
echo 1500000 > "$P"
sleep 0.2
echo after_1.5A_reg35=$(i2cget -y -f "$BUSNO" "$ADDR" 0x35 2>/dev/null) icl=$(cat $P)
echo 2000000 > "$P"
sleep 0.2
echo after_2A_reg35=$(i2cget -y -f "$BUSNO" "$ADDR" 0x35 2>/dev/null) icl=$(cat $P)
B=/sys/class/power_supply/axp288_fuel_gauge
echo status=$(cat $B/status) I=$(cat $B/current_now)
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/axp-i2c.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/axp-i2c.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/axp-i2c.sh", timeout=30)
    print(stdout.read().decode())
    err = stderr.read().decode()
    if err.strip():
        print("STDERR:", err[:600])
    c.close()


if __name__ == "__main__":
    main()
