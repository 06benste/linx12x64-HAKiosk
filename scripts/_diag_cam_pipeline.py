#!/usr/bin/env python3
from __future__ import annotations

import paramiko
import sys

HOST, PASS = "192.168.8.201", "kiosk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)

    def run(cmd: str) -> None:
        print("====", cmd[:100], flush=True)
        _, o, e = c.exec_command(f"echo {PASS} | sudo -S -p '' bash -lc {repr(cmd)}", timeout=60, get_pty=True)
        print(o.read().decode("utf-8", "replace")[-8000:])

    run("systemctl status ha-kiosk-camera-stream --no-pager -l | head -n 40")
    run("curl -fsS http://127.0.0.1:17824/status")
    run("v4l2-ctl -d /dev/video0 --all 2>&1 | head -n 80")
    run("ps aux | grep -E 'v4l2-ctl|ffmpeg|camera-stream' | grep -v grep")
    run("ls -la /dev/video* 2>&1; dmesg | grep -iE 'atomisp|gc2355|camera|ov' | tail -n 40")
    run("journalctl -u ha-kiosk-camera-stream -b --no-pager | tail -n 50")
    c.close()


if __name__ == "__main__":
    main()
