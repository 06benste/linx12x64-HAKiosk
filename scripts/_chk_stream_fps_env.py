#!/usr/bin/env python3
from __future__ import annotations
import paramiko, sys
HOST, PASS = "192.168.8.201", "kiosk"
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
_,o,_=c.exec_command(f"echo {PASS} | sudo -S -p '' bash -lc {repr('grep -E \"CAMERA_STREAM|FPS|WIDTH|HEIGHT|QUALITY\" /opt/ha-kiosk/mqtt.env /etc/systemd/system/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-mqtt.service 2>/dev/null; echo ---; systemctl show ha-kiosk-camera-stream -p Environment --no-pager; echo ---; journalctl -u ha-kiosk-mqtt -n 5 --no-pager | grep -i stream || true')}", timeout=30, get_pty=True)
print(o.read().decode("utf-8","replace"))
c.close()
