#!/usr/bin/env python3
"""Wait for hakiosk SSH, then gather crash evidence."""
from __future__ import annotations

import sys
import time

import paramiko

HOST = "192.168.8.201"
USER = "kioskuser"
PASS = "kiosk"

CMDS = [
    "uptime",
    "last -x | head -n 25",
    "cat /proc/cmdline",
    "echo '--- bash_profile ---'; cat ~/.bash_profile 2>/dev/null || echo none",
    "echo '--- xinitrc ---'; cat ~/.xinitrc 2>/dev/null || echo none",
    "ps aux | grep -E 'cage|chromium|Xorg|startx' | grep -v grep || echo no-display-procs",
    "ls -l /dev/dri 2>/dev/null || echo no-dri",
    "free -h",
    "systemctl is-active ha-kiosk-inhibit-sleep.service ha-kiosk-noblank.service 2>/dev/null; systemctl is-enabled sleep.target suspend.target 2>/dev/null || true",
    "echo kiosk | sudo -S -p '' journalctl -b -1 -k --no-pager 2>/dev/null | tail -n 60 || true",
    "echo kiosk | sudo -S -p '' journalctl -b -1 --no-pager 2>/dev/null | grep -iE 'panic|oops|bug:|i915|gpu|hang|watchdog|oom|killed|segfault|cage|chromium' | tail -n 80 || true",
    "dmesg -T 2>/dev/null | grep -iE 'i915|gpu|hang|watchdog|oom|error|fail' | tail -n 40 || true",
]


def wait_ssh(timeout: int = 2700) -> paramiko.SSHClient:
    deadline = time.time() + timeout
    last_err: Exception | None = None
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                HOST,
                username=USER,
                password=PASS,
                timeout=8,
                banner_timeout=20,
                auth_timeout=20,
                allow_agent=False,
                look_for_keys=False,
            )
            print(f"SSH connected on attempt {attempt}", flush=True)
            return client
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt == 1 or attempt % 6 == 0:
                print(f"SSH wait #{attempt}: {exc}", flush=True)
            time.sleep(5)
    raise RuntimeError(f"SSH never came up: {last_err}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Waiting for SSH (up to 45 min)...", flush=True)
    client = wait_ssh(2700)
    for cmd in CMDS:
        print(f"\n===== {cmd[:90]} =====", flush=True)
        stdin, stdout, stderr = client.exec_command(cmd, timeout=90)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        print(out.rstrip() or "(empty)", flush=True)
        if err.strip() and "password" not in err.lower():
            print("STDERR:", err.rstrip()[:2000], flush=True)
    client.close()
    print("\nDIAGNOSE_DONE", flush=True)


if __name__ == "__main__":
    main()
