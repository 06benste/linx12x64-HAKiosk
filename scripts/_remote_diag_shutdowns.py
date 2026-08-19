#!/usr/bin/env python3
"""Diagnose unexpected tablet shutdowns from system logs."""
from __future__ import annotations

import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo '=== uptime / who / last ==='
uptime
who -b 2>/dev/null || true
last -x | head -n 40
echo
echo '=== recent shutdown/reboot journal ==='
journalctl -b -1 -n 80 --no-pager 2>/dev/null || echo '(no previous boot journal)'
echo
echo '=== current boot: power / thermal / shutdown ==='
journalctl -b 0 -p warning..alert --no-pager | tail -n 120
echo
echo '=== keywords this boot ==='
journalctl -b 0 --no-pager | grep -iE 'shutdown|power.?off|thermal|overheat|critical|oom|Out of memory|Watchdog|BUG:|panic|GPU hang|i915|axp|battery|low.?batt|undervolt|brownout|Restarting|Stopping|halt|acpi|PBTN|Power Button' | tail -n 80
echo
echo '=== previous boot keywords ==='
journalctl -b -1 --no-pager 2>/dev/null | grep -iE 'shutdown|power.?off|thermal|overheat|critical|oom|Out of memory|Watchdog|BUG:|panic|GPU hang|i915|axp|battery|Restarting|Stopping|halt|acpi|PBTN|Power Button|chromium|kiosk' | tail -n 100
echo
echo '=== systemd failed / crashed units ==='
systemctl --failed --no-pager
echo
echo '=== last -x crash/reboot summary ==='
last -x reboot shutdown crash power | head -n 30
echo
echo '=== battery / power now ==='
python3 - <<'PY'
import json, urllib.request
try:
  st=json.load(urllib.request.urlopen('http://127.0.0.1:17823/status', timeout=4))
  print(json.dumps({k: st.get(k) for k in ('power','thermal','uptime','hostname')}, indent=2))
except Exception as e:
  print('api', e)
PY
echo
echo '=== dmesg thermal/power tail ==='
dmesg -T 2>/dev/null | grep -iE 'thermal|temp|axp|battery|undervolt|oom|kill|i915|gpu|hang|reset' | tail -n 50
echo
echo '=== cron / timers that could poweroff ==='
systemctl list-timers --all --no-pager | head -n 40
crontab -l 2>/dev/null; ls /etc/cron.* 2>/dev/null
grep -rsl 'poweroff\|shutdown\|halt\|systemctl.*power' /etc/cron* /var/spool/cron 2>/dev/null | head
echo
echo '=== ha-kiosk services ==='
systemctl is-active ha-kiosk-power.service ha-kiosk-mqtt.service getty@tty1.service 2>/dev/null
journalctl -u ha-kiosk-power.service -u ha-kiosk-mqtt.service -b 0 --no-pager | grep -iE 'shutdown|reboot|power|error|fail' | tail -n 40
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"SSH connect failed to {HOST}: {exc}")
        # try alternate IP from earlier context
        for alt in ("192.168.8.202", "hakiosk.local"):
            try:
                print(f"trying {alt}...")
                c.connect(alt, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
                break
            except Exception as e2:
                print(f"  failed: {e2}")
        else:
            raise SystemExit(1)
    sftp = c.open_sftp()
    with sftp.file("/tmp/shutdown-diag.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/shutdown-diag.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/shutdown-diag.sh", timeout=90
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1500:])
    c.close()


if __name__ == "__main__":
    main()
