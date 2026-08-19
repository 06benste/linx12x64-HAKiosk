#!/usr/bin/env python3
from __future__ import annotations

import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""
set -x
uptime
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service || true
systemctl status ha-kiosk-mqtt.service --no-pager -l | head -25 || true
journalctl -u ha-kiosk-mqtt.service -n 30 --no-pager || true
ping -c1 -W2 192.168.8.110 >/dev/null && echo BROKER_OK || echo BROKER_FAIL
ss -lntp | grep -E '17823|17824' || true
# force mqtt back up
systemctl reset-failed ha-kiosk-mqtt.service || true
systemctl restart ha-kiosk-mqtt.service || true
sleep 3
systemctl is-active ha-kiosk-mqtt.service || true
journalctl -u ha-kiosk-mqtt.service -n 15 --no-pager || true
"""


def main() -> None:
    for u in (
        f"http://{HOST}:17823/health",
        f"http://{HOST}:17824/health",
    ):
        try:
            print(u, urllib.request.urlopen(u, timeout=3).read()[:160])
        except Exception as e:
            print(u, type(e).__name__, e)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        c.connect(
            HOST,
            username="kioskuser",
            password=PASS,
            timeout=12,
            allow_agent=False,
            look_for_keys=False,
        )
    except Exception as e:
        print("ssh connect failed:", type(e).__name__, e)
        return

    sftp = c.open_sftp()
    with sftp.file("/tmp/fix-mqtt.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-mqtt.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/fix-mqtt.sh",
        timeout=90,
        get_pty=True,
    )
    stdout.channel.settimeout(75)
    try:
        print(stdout.read().decode(errors="replace"))
    except Exception as e:
        print("ssh read:", type(e).__name__, e)
    try:
        print("exit", stdout.channel.recv_exit_status())
    except Exception:
        pass
    c.close()


if __name__ == "__main__":
    main()
