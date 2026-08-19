#!/usr/bin/env python3
import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password="kiosk", timeout=15, allow_agent=False, look_for_keys=False)
_, o, _ = c.exec_command(
    "echo kiosk | sudo -S -p '' bash -c 'systemctl start ha-kiosk-camera-stream.service; systemctl start ha-kiosk-mqtt.service; sleep 4; systemctl is-active ha-kiosk-camera-stream ha-kiosk-mqtt; ss -lntp | grep 17824 || true'",
    timeout=40,
    get_pty=True,
)
print(o.read().decode())
c.close()
