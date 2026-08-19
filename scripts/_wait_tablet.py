#!/usr/bin/env python3
import socket
import time

import paramiko

HOSTS = ["192.168.8.201", "hakiosk"]
PASS = "kiosk"

for attempt in range(12):
    for host in HOSTS:
        try:
            ip = socket.gethostbyname(host)
        except Exception:
            ip = host
        print(f"try {attempt} {host} ({ip})")
        try:
            sock = socket.create_connection((ip, 22), timeout=4)
            sock.close()
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(ip, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
            _, o, _ = c.exec_command("uptime; systemctl is-active ha-kiosk-camera-stream.service || true", timeout=20)
            print(o.read().decode())
            c.close()
            print("REACHABLE", ip)
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as e:
            print(" ", type(e).__name__, e)
    time.sleep(5)
raise SystemExit("tablet still unreachable")
