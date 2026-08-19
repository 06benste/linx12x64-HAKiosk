#!/usr/bin/env python3
"""Pull boot errors / cherryview-pinctrl from hakiosk."""
from __future__ import annotations

import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

REMOTE = r"""
set -euo pipefail
echo '=== uptime / boot ==='
uptime
who -b 2>/dev/null || true
echo
echo '=== cherryview / pinctrl (dmesg) ==='
dmesg -T 2>/dev/null | grep -iE 'cherryview|pinctrl|chv-|INT33FF|gpio' | head -n 80 || true
echo
echo '=== cherryview / pinctrl (journal this boot) ==='
journalctl -b -o short-precise --no-pager 2>/dev/null | grep -iE 'cherryview|pinctrl|chv-|INT33FF' | head -n 80 || true
echo
echo '=== boot errors/warnings (priority err..alert) ==='
journalctl -b -p err..alert --no-pager -o short-precise 2>/dev/null | head -n 120 || true
echo
echo '=== notable failed units ==='
systemctl --failed --no-pager 2>/dev/null || true
echo
echo '=== kernel cmdline ==='
cat /proc/cmdline
echo
echo '=== last 40 dmesg warnings/errors ==='
dmesg -T --level=err,warn 2>/dev/null | tail -n 40 || dmesg -T 2>/dev/null | grep -iE 'error|fail|warn' | tail -n 40 || true
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/boot_errs.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/boot_errs.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/boot_errs.sh", timeout=90, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
