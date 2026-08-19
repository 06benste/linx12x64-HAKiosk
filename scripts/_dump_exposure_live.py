#!/usr/bin/env python3
"""Dump GC2355 exposure/gain while the MJPEG stream is live."""
from __future__ import annotations

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

REMOTE = r"""
set -euxo pipefail
modprobe i2c-dev || true
# Ensure stream is up
systemctl start ha-kiosk-camera-stream.service || true
# Wake a client so v4l actually streams
python3 - <<'PY'
import threading, time, urllib.request
def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(2048)
    except Exception as e: print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
print('clients woken')
PY

python3 - <<'PY'
from pathlib import Path
import subprocess

def buses():
    out = []
    for d in sorted(Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*')):
        real = d.resolve()
        bus = None
        for p in str(real).split('/'):
            if p.startswith('i2c-') and p[4:].isdigit():
                bus = int(p[4:])
        out.append((d.name, bus, str(real)))
        print(f'device {d.name} bus={bus} path={real}')
    return out

def iget(bus, reg):
    r = subprocess.run(['i2cget','-y',str(bus),'0x3c',hex(reg)], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return int(r.stdout.strip(), 16)

def iset(bus, reg, val):
    r = subprocess.run(['i2cset','-y',str(bus),'0x3c',hex(reg),hex(val)], capture_output=True, text=True)
    return r.returncode == 0

def dump(bus, label):
    # page 0
    iset(bus, 0xfe, 0x00)
    regs = [0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0a,0x0d,0x0e,0x0f,0x10,
            0xb0,0xb1,0xb2,0xb3,0xb4,0xb5,0xb6]
    print(f'--- {label} bus={bus} page0 ---')
    for r in regs:
        v = iget(bus, r)
        print(f'  0x{r:02x}=0x{v:02x}' if v is not None else f'  0x{r:02x}=FAIL')
    exp = None
    eh, el = iget(bus, 0x03), iget(bus, 0x04)
    if eh is not None and el is not None:
        exp = (eh << 8) | el
        print(f'  exposure_lines={exp} (0x{exp:04x})')
    # page 1 sometimes holds more
    iset(bus, 0xfe, 0x01)
    print(f'--- {label} bus={bus} page1 sample ---')
    for r in [0x03,0x04,0xb0,0xb1,0xb2,0xb6]:
        v = iget(bus, r)
        print(f'  p1 0x{r:02x}=0x{v:02x}' if v is not None else f'  p1 0x{r:02x}=FAIL')
    iset(bus, 0xfe, 0x00)

devs = buses()
for name, bus, _ in devs:
    if bus is None:
        continue
    # only dump if chip id responds
    iset(bus, 0xfe, 0x00)
    h, l = iget(bus, 0xf0), iget(bus, 0xf1)
    print(f'{name} id={h} {l}')
    if h is None:
        continue
    dump(bus, name)

# Also list media/v4l subdevs
import os
print('=== video nodes ===')
os.system('ls -l /dev/video* /dev/v4l-subdev* 2>/dev/null || true')
os.system('v4l2-ctl --list-devices 2>/dev/null || true')
print('=== atomisp headers ===')
os.system('find /usr/src /usr/include -name atomisp.h 2>/dev/null | head')
os.system('find /usr/src -name atomisp-gc2235.c 2>/dev/null | head')
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/dump_exp.sh", "w") as f:
    f.write(REMOTE)
sftp.chmod("/tmp/dump_exp.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/dump_exp.sh", timeout=90, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
