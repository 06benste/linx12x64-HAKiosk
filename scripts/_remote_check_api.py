#!/usr/bin/env python3
import sys
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password="kiosk", timeout=15, allow_agent=False, look_for_keys=False)
script = r"""#!/bin/bash
set -x
systemctl restart ha-kiosk-power.service ha-kiosk-mqtt.service
sleep 2
systemctl is-active ha-kiosk-power.service ha-kiosk-mqtt.service
ss -ltnp | grep 17823 || true
python3 - <<'PY'
import urllib.request
print('local', urllib.request.urlopen('http://127.0.0.1:17823/health', timeout=3).read())
print('lan', urllib.request.urlopen('http://192.168.8.201:17823/health', timeout=3).read())
PY
journalctl -u ha-kiosk-power.service -n 30 --no-pager
echo '--- mqtt ---'
journalctl -u ha-kiosk-mqtt.service -n 30 --no-pager
grep -n 'HOST\|0.0.0.0\|127.0.0.1' /opt/ha-kiosk/scripts/power-api.py | head
"""
sftp = c.open_sftp()
with sftp.file("/tmp/check-api.sh", "w") as f:
    f.write(script)
sftp.chmod("/tmp/check-api.sh", 0o755)
sftp.close()
stdin, stdout, stderr = c.exec_command("echo kiosk | sudo -S -p '' bash /tmp/check-api.sh", timeout=40)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print(stdout.read().decode())
print(stderr.read().decode()[:2500])
c.close()
