#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo '=== previous boot END (last 60 lines) ==='
journalctl -b -1 -n 60 --no-pager 2>/dev/null
echo
echo '=== previous boot start + duration ==='
journalctl -b -1 -n 5 --no-pager 2>/dev/null | head -5
journalctl -b -1 -o short-iso --no-pager 2>/dev/null | head -1
journalctl -b -1 -o short-iso --no-pager 2>/dev/null | tail -1
echo
echo '=== lid / sleep / logind config ==='
systemctl status sleep.target suspend.target hibernate.target hybrid-sleep.target --no-pager 2>&1 | head -40
cat /etc/systemd/logind.conf 2>/dev/null | grep -v '^#' | grep -v '^$'
ls /etc/systemd/logind.conf.d 2>/dev/null
cat /etc/systemd/logind.conf.d/* 2>/dev/null
echo 'HandleLidSwitch related:'
grep -r Handle /etc/systemd/logind.conf /etc/systemd/logind.conf.d 2>/dev/null
echo
echo '=== masked sleep? ==='
systemctl is-enabled sleep.target suspend.target hibernate.target 2>&1
systemctl list-unit-files '*sleep*' '*suspend*' '*hibernate*' --no-pager 2>&1 | head
echo
echo '=== what is runuser every 15s? ==='
ps aux | grep -iE 'runuser|kiosk|chromium|watch|loop' | grep -v grep | head -40
systemctl list-units --type=service --state=running --no-pager | grep -iE 'kiosk|chrom|x11|display'
echo '--- kiosk x11 / getty related ---'
ls /etc/systemd/system/*kiosk* /etc/systemd/system/*x11* 2>/dev/null
for u in /etc/systemd/system/*kiosk* /etc/systemd/system/getty@tty1.service.d/*; do
  [ -e "$u" ] || continue
  echo "==== $u ===="
  cat "$u" 2>/dev/null
done
echo
echo '=== power supply sysfs ==='
for p in /sys/class/power_supply/*; do
  echo "-- $p --"
  for f in type online status present capacity voltage_now current_now voltage_min_design technology manufacturer model_name; do
    [ -f "$p/$f" ] && printf '  %s=%s\n' "$f" "$(cat "$p/$f" 2>/dev/null)"
  done
done
echo
echo '=== axp / charger details ==='
find /sys -iname '*axp*' 2>/dev/null | head -40
for f in /sys/class/power_supply/*/uevent; do echo "==== $f ===="; cat "$f"; done
echo
echo '=== low battery / critical actions ==='
grep -rsl . /etc/UPower /etc/systemd 2>/dev/null | head
cat /etc/UPower/UPower.conf 2>/dev/null | grep -v '^#' | grep -v '^$'
systemctl is-active upower 2>&1
echo
echo '=== pstore ==='
ls -la /sys/fs/pstore /var/lib/systemd/pstore 2>/dev/null
echo
echo '=== overnight battery from previous boot logs ==='
journalctl -b -1 --no-pager 2>/dev/null | grep -iE 'battery|axp|low.?batt|critical|Discharging|capacity|charger|Vbus|extcon' | tail -n 40
echo
echo '=== i915 / GPU hang previous boot ==='
journalctl -b -1 --no-pager 2>/dev/null | grep -iE 'i915|GPU|hang|reset|drm|chrome|chromium|segfault|oom' | tail -n 50
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/shutdown-diag2.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/shutdown-diag2.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/shutdown-diag2.sh", timeout=90
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-800:])
    c.close()


if __name__ == "__main__":
    main()
