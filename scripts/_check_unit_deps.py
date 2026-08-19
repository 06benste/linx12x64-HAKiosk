#!/usr/bin/env python3
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""
set -x
echo '=== unit deps ==='
systemctl show ha-kiosk-mqtt.service -p After -p Before -p Wants -p Requires -p WantedBy || true
systemctl show ha-kiosk-camera-stream.service -p After -p Before -p Wants -p Requires -p WantedBy || true
systemctl show ha-kiosk-atomisp.service -p After -p Before -p Wants -p Requires -p WantedBy || true
echo '=== analyze ==='
systemd-analyze verify ha-kiosk-mqtt.service ha-kiosk-camera-stream.service ha-kiosk-atomisp.service 2>&1 || true
echo '=== why-not-started (boot) ==='
journalctl -b 0 -u ha-kiosk-mqtt.service -u ha-kiosk-camera-stream.service --no-pager | head -80 || true
echo '=== cat units ==='
grep -E '^(After|Before|Wants|Requires|WantedBy|Description)' /etc/systemd/system/ha-kiosk-mqtt.service /etc/systemd/system/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-atomisp.service 2>/dev/null || true
"""


def main() -> None:
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/deps.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deps.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deps.sh", timeout=45, get_pty=True)
    print(o.read().decode("utf-8", errors="replace"))
    c.close()


if __name__ == "__main__":
    main()
