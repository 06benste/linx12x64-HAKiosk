#!/usr/bin/env python3
import json
import sys
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""#!/bin/bash
set +e
P=/sys/class/power_supply/axp288_charger
B=/sys/class/power_supply/axp288_fuel_gauge
echo '=== extcon ==='
cat /sys/class/extcon/extcon0/state 2>/dev/null
echo
echo '=== samples ==='
for i in 1 2 3 4 5; do
  printf '%d online=%s icl=%s status=%s cap=%s I=%s V=%s\n' "$i" \
    "$(cat "$P/online")" "$(cat "$P/input_current_limit")" \
    "$(cat "$B/status")" "$(cat "$B/capacity")" \
    "$(cat "$B/current_now")" "$(cat "$B/voltage_now")"
  sleep 2
done
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== API ===")
    try:
        st = json.load(urllib.request.urlopen(f"http://{HOST}:17823/status", timeout=8))
        print(json.dumps(st.get("power"), indent=2))
    except Exception as exc:
        print("API fail:", exc)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/chg-now.sh", "w") as f:
        f.write(REMOTE)
    sftp.chmod("/tmp/chg-now.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/chg-now.sh", timeout=40)
    print(stdout.read().decode())
    c.close()


if __name__ == "__main__":
    main()
