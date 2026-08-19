#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
import urllib.request

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    # Run measurement on-device so local network isn't involved.
    script = r"""
import json, time, urllib.request, threading, subprocess

def suck():
    try:
        r = urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=40)
        while True:
            if not r.read(8192):
                break
    except Exception as e:
        print('suck_end', e)

t = threading.Thread(target=suck, daemon=True)
t.start()
time.sleep(4)
h1 = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
t0 = time.monotonic()
time.sleep(8)
h2 = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
dt = time.monotonic() - t0
df = max(0, int(h2.get('frames',0)) - int(h1.get('frames',0)))
print('h1', h1)
print('h2', h2)
print(f'sustained_fps={df/dt:.2f} delta={df} dt={dt:.2f}')
print(subprocess.getoutput("ps -o pid,pcpu,pmem,etime,cmd -C python3,ffmpeg,v4l2-ctl | head -n 20"))
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/meas_fps.py", "w") as f:
        f.write(script)
    sftp.close()
    _, o, e = c.exec_command("python3 /tmp/meas_fps.py", timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err)
    c.close()


if __name__ == "__main__":
    main()
