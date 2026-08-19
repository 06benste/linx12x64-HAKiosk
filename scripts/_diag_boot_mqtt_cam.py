#!/usr/bin/env python3
"""Diagnose MQTT + camera services after reboot."""
from __future__ import annotations

import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

REMOTE = r"""
set -uo pipefail
echo '=== uptime / boot ==='
uptime
who -b 2>/dev/null || true
echo
echo '=== unit states ==='
systemctl is-enabled ha-kiosk-mqtt.service ha-kiosk-camera-stream.service ha-kiosk-power.service ha-kiosk-atomisp.service 2>&1 || true
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service ha-kiosk-power.service ha-kiosk-atomisp.service 2>&1 || true
echo
echo '=== systemctl status ==='
for u in ha-kiosk-mqtt ha-kiosk-camera-stream ha-kiosk-power ha-kiosk-atomisp; do
  echo "--- $u ---"
  systemctl status "$u.service" --no-pager -l 2>&1 | head -25 || true
done
echo
echo '=== failed / dead jobs ==='
systemctl --failed --no-pager || true
systemctl list-jobs --no-pager 2>&1 | head -40 || true
echo
echo '=== ordering cycle hints ==='
journalctl -b -u ha-kiosk-mqtt.service -u ha-kiosk-camera-stream.service -u ha-kiosk-atomisp.service -u multi-user.target --no-pager 2>&1 | grep -iE 'cycle|deleted|failed|Started|Stopped|inactive|dependency' | tail -60
echo
echo '=== recent mqtt/camera journals ==='
journalctl -u ha-kiosk-mqtt.service -b --no-pager -n 40
echo
journalctl -u ha-kiosk-camera-stream.service -b --no-pager -n 40
echo
echo '=== unit files ==='
for u in ha-kiosk-mqtt ha-kiosk-camera-stream ha-kiosk-atomisp; do
  echo "=== $u.service ==="
  systemctl cat "$u.service" 2>&1 | head -40 || true
done
echo
echo '=== camera_power / video ==='
cat /opt/ha-kiosk/config/camera_power 2>/dev/null || echo missing
ls -la /dev/video0 2>&1 || true
"""

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/diag-boot-services.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/diag-boot-services.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/diag-boot-services.sh",
        timeout=90,
        get_pty=True,
    )
    print(o.read().decode("utf-8", "replace"))
    c.close()

if __name__ == "__main__":
    main()
