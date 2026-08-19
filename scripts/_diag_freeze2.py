#!/usr/bin/env python3
import json
import time
import urllib.request

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)

# Sample health twice to see if frames advance
for i in range(3):
    _, o, _ = c.exec_command("curl -fsS --max-time 3 http://127.0.0.1:17824/health", timeout=10)
    h = o.read().decode()
    print(f"t{i}", h)
    time.sleep(2)

# ffmpeg stderr fd size / blocked?
_, o, _ = c.exec_command(
    "echo kiosk | sudo -S -p '' bash -lc "
    "'ls -l /proc/2707/fd 2>/dev/null | head; "
    "wc -c /proc/2707/fd/2 2>/dev/null; "
    "ls -l /proc/2706/fd/1 2>/dev/null; "
    "cat /proc/2706/status | grep -E State|Threads; "
    "cat /proc/2707/status | grep -E State|Threads'",
    timeout=15,
    get_pty=True,
)
print(o.read().decode())
c.close()
