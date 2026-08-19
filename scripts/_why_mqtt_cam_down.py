#!/usr/bin/env python3
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""
set -x
echo '=== unit status ==='
systemctl status ha-kiosk-mqtt.service ha-kiosk-camera-stream.service --no-pager -l || true
echo '=== is-enabled ==='
systemctl is-enabled ha-kiosk-mqtt.service ha-kiosk-camera-stream.service ha-kiosk-atomisp.service ha-kiosk-power.service 2>&1 || true
echo '=== failed units ==='
systemctl --failed --no-pager || true
echo '=== mqtt journal ==='
journalctl -u ha-kiosk-mqtt.service -n 40 --no-pager || true
echo '=== stream journal ==='
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager || true
echo '=== atomisp / power ==='
systemctl is-active ha-kiosk-atomisp.service ha-kiosk-power.service 2>&1 || true
journalctl -u ha-kiosk-atomisp.service -n 15 --no-pager || true
echo '=== boot ==='
who -b || true
uptime
ls -la /dev/video0 /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py /opt/ha-kiosk/mqtt.env 2>&1 || true
"""


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/why-down.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/why-down.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/why-down.sh", timeout=60, get_pty=True)
    print(o.read().decode("utf-8", errors="replace"))
    c.close()


if __name__ == "__main__":
    main()
