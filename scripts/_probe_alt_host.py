#!/usr/bin/env python3
"""Probe unexpected SSH hosts briefly."""
import paramiko

for host in ("192.168.8.104",):
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(host, username="kioskuser", password="kiosk", timeout=8, allow_agent=False, look_for_keys=False)
        _, o, _ = c.exec_command("hostname; cat /etc/hostname 2>/dev/null; uname -a", timeout=10)
        print(host, o.read().decode())
        c.close()
    except Exception as e:
        print(host, type(e).__name__, e)
