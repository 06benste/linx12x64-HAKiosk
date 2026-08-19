#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
P=/sys/class/power_supply/axp288_charger
echo '=== charger attrs ==='
ls -la "$P"
for f in "$P"/*; do
  [ -f "$f" ] || continue
  [ -r "$f" ] || continue
  printf '%s=%s\n' "$(basename "$f")" "$(cat "$f" 2>/dev/null | tr '\n' ' ')"
done
echo
echo '=== try raise input_current_limit ==='
echo before: $(cat "$P/input_current_limit")
# Common values: 500000, 900000, 1500000, 2000000, 3000000
for v in 1500000 2000000 2400000 900000; do
  echo "$v" > "$P/input_current_limit" 2>/tmp/icl.err && echo "set $v OK" && break || echo "set $v FAIL: $(cat /tmp/icl.err)"
done
echo after: $(cat "$P/input_current_limit")
sleep 2
echo '=== battery after bump ==='
B=/sys/class/power_supply/axp288_fuel_gauge
for f in status capacity voltage_now current_now; do
  printf '%s=%s\n' "$f" "$(cat "$B/$f")"
done
echo online=$(cat "$P/online")
echo
echo '=== low batt events all boots ==='
journalctl --no-pager 2>/dev/null | grep -i 'Low Batt' | tail -n 20
echo
echo '=== boot timeline with battery if any ==='
# sample power from mqtt retained? skip
python3 - <<'PY'
import time, pathlib
chg=pathlib.Path('/sys/class/power_supply/axp288_charger')
bat=pathlib.Path('/sys/class/power_supply/axp288_fuel_gauge')
for i in range(5):
  print(i, 'icl=', (chg/'input_current_limit').read_text().strip(),
        'status=', (bat/'status').read_text().strip(),
        'cap=', (bat/'capacity').read_text().strip(),
        'I=', (bat/'current_now').read_text().strip(),
        'V=', (bat/'voltage_now').read_text().strip())
  time.sleep(1)
PY
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/chg-fix.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/chg-fix.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/chg-fix.sh", timeout=40
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-600:])
    c.close()


if __name__ == "__main__":
    main()
