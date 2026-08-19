#!/usr/bin/env python3
from __future__ import annotations

import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"

REMOTE = r"""
set -euxo pipefail
echo '=== xauth ==='
ls -la /home/kioskuser/.Xauthority 2>/dev/null || echo no-xauth
echo '=== xset q DPMS ==='
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority xset q 2>&1 | tee /tmp/xset-q.txt | tail -50
echo '=== blank ==='
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority xset dpms force off || true
sleep 1
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority xset q 2>&1 | tee /tmp/xset-q-off.txt | grep -i -A6 DPMS || true
echo '=== wake ==='
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority xset dpms force on || true
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority xset s reset || true
sleep 1
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority xset q 2>&1 | tee /tmp/xset-q-on.txt | grep -i -A6 DPMS || true
echo '=== api ==='
curl -fsS http://127.0.0.1:17823/status | python3 -c 'import sys,json; print(json.load(sys.stdin).get("display"))'
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/probe-dpms.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/probe-dpms.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/probe-dpms.sh", timeout=60, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    c.close()


if __name__ == "__main__":
    main()
