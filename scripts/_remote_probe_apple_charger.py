#!/usr/bin/env python3
"""Probe AXP288 charge path with Apple/iPad-style charger attached."""
from __future__ import annotations

import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo '=== reachability / uptime ==='
uptime
echo
echo '=== extcon / charger / battery ==='
for n in /sys/class/extcon/*; do
  echo "extcon $(basename $n): name=$(cat $n/name 2>/dev/null)"
  cat "$n/state" 2>/dev/null
  echo
done
P=/sys/class/power_supply/axp288_charger
B=/sys/class/power_supply/axp288_fuel_gauge
echo '--- charger ---'
for f in online present health type input_current_limit constant_charge_current constant_charge_voltage; do
  [ -f "$P/$f" ] && echo "$f=$(cat $P/$f)"
done
echo '--- battery ---'
for f in status capacity voltage_now current_now charge_now charge_full health technology; do
  [ -f "$B/$f" ] && echo "$f=$(cat $B/$f)"
done
echo
echo '=== debugfs / charge enable if any ==='
find /sys -path '*axp288*' \( -iname '*enable*' -o -iname '*charge*' -o -iname '*inlmt*' -o -iname '*vbus*' \) 2>/dev/null | head -60
echo
# Try force ICL high and see if status flips over ~20s
echo '=== force ICL 2.0A then 2.4A and sample ==='
for v in 2000000 2400000; do
  echo "$v" > "$P/input_current_limit" 2>/dev/null && echo "set $v" || echo "fail $v"
done
for i in 1 2 3 4 5 6 7 8; do
  printf '%02d icl=%s status=%s cap=%s I=%s V=%s online=%s\n' "$i" \
    "$(cat $P/input_current_limit)" "$(cat $B/status)" "$(cat $B/capacity)" \
    "$(cat $B/current_now)" "$(cat $B/voltage_now)" "$(cat $P/online)"
  sleep 2
done
echo
echo '=== dmesg recent axp/charge ==='
dmesg -T 2>/dev/null | grep -iE 'axp|charg|extcon|vbus|SDP|DCP|CDP' | tail -n 30
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"SSH failed {HOST}: {exc}")
        for alt in ("192.168.8.202",):
            try:
                c.connect(alt, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
                print(f"connected via {alt}")
                break
            except Exception as e2:
                print(f"  {alt}: {e2}")
        else:
            raise SystemExit(1)
    sftp = c.open_sftp()
    with sftp.file("/tmp/apple-chg.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/apple-chg.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/apple-chg.sh", timeout=60
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-800:])
    c.close()


if __name__ == "__main__":
    main()
