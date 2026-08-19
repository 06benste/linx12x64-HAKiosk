#!/usr/bin/env python3
"""Force i2c access to GC2355 while streaming; dump + bump exposure/gain."""
from __future__ import annotations

import io
import json
import pathlib
import time

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
modprobe i2c-dev || true
systemctl start ha-kiosk-camera-stream.service || true
python3 - <<'PY'
import threading, time, urllib.request
def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=25).read(4096)
    except Exception as e: print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
print('stream woken')
PY

python3 - <<'PY'
import subprocess, time, io, json, urllib.request, threading
from pathlib import Path
from PIL import Image, ImageStat

ADDR = 0x3c

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def iget(bus, reg):
    # -f force even if driver owns the device
    r = run(['i2cget','-y','-f',str(bus),hex(ADDR),hex(reg)])
    if r.returncode != 0:
        return None
    return int(r.stdout.strip(), 16)

def iset(bus, reg, val):
    r = run(['i2cset','-y','-f',str(bus),hex(ADDR),hex(reg),hex(val)])
    return r.returncode == 0, r.stderr.strip()

def page0(bus):
    iset(bus, 0xfe, 0x00)

def dump(bus, label):
    page0(bus)
    regs = [0x03,0x04,0x05,0x06,0x07,0x08,0x0d,0x0e,0xb0,0xb1,0xb2,0xb6,0x26]
    print(f'=== {label} bus={bus} ===')
    vals = {}
    for r in regs:
        v = iget(bus, r)
        vals[r] = v
        print(f'  0x{r:02x}={"FAIL" if v is None else hex(v)}')
    if vals.get(0x03) is not None and vals.get(0x04) is not None:
        exp = (vals[0x03]<<8)|vals[0x04]
        print(f'  exposure={exp}')
    return vals

def snap(name):
    def suck():
        try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=15).read(1024)
        except Exception: pass
    threading.Thread(target=suck, daemon=True).start()
    time.sleep(2.5)
    data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
    open(name,'wb').write(data)
    im = Image.open(io.BytesIO(data)).convert('RGB')
    st = ImageStat.Stat(im)
    print(name, 'mean', [round(x,1) for x in st.mean], 'bytes', len(data))
    return st.mean

# Find working bus
buses = []
for d in sorted(Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*')):
    real = d.resolve()
    bus=None
    for p in str(real).split('/'):
        if p.startswith('i2c-') and p[4:].isdigit():
            bus=int(p[4:])
    buses.append((d.name, bus))
    print('dev', d.name, 'bus', bus)

active=None
for name, bus in buses:
    if bus is None: continue
    page0(bus)
    h = iget(bus, 0xf0)
    l = iget(bus, 0xf1)
    print(f'{name} force-id h={h} l={l}')
    if h is not None:
        active = bus
        break

if active is None:
    # brute all i2c adapters
    for bus in range(0, 12):
        page0(bus)
        h = iget(bus, 0xf0)
        if h is not None:
            print('found on bus', bus, 'id', h, iget(bus,0xf1))
            active = bus
            break

if active is None:
    raise SystemExit('no i2c access to sensor')

before = dump(active, 'BEFORE')
snap('/tmp/ha_before_hw.jpg')

# Aggressive low-light: raise VBI so exposure can exceed ~1200 lines, then max exposure + gain
# VB regs 0x07/0x08 — bump blanking (slower fps, more light)
page0(active)
# Keep existing HB; set VB ~0x0200 (~512 lines extra)
iset(active, 0x07, 0x02)
iset(active, 0x08, 0x00)
# Exposure ~0x0A00 (2560 lines) — needs the extra VBI
iset(active, 0x03, 0x09)
iset(active, 0x04, 0xC0)
# Gains from Rockchip low-light-ish values, then push higher
iset(active, 0xb0, 0x60)   # global
iset(active, 0xb1, 0x04)
iset(active, 0xb2, 0x00)   # digi/pre
iset(active, 0xb6, 0x06)   # analog gain step (0..0x0f typical)
# also try analog path used in atomisp table
iset(active, 0x26, 0x03)

time.sleep(1.0)
after = dump(active, 'AFTER_WRITE')
# verify stickiness after a couple frames
time.sleep(2.0)
after2 = dump(active, 'AFTER_2S')
snap('/tmp/ha_after_hw.jpg')

# If AE in ISP reverts, values change — report that
print('sticky_exp', after.get(0x03)==after2.get(0x03) and after.get(0x04)==after2.get(0x04))
print('sticky_b6', after.get(0xb6)==after2.get(0xb6))
print('DONE')
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/force_exp.sh", "w") as f:
    f.write(REMOTE)
sftp.chmod("/tmp/force_exp.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/force_exp.sh", timeout=120, get_pty=True)
print(o.read().decode("utf-8", "replace"))
code = o.channel.recv_exit_status()
sftp = c.open_sftp()
for src, dst in [("/tmp/ha_before_hw.jpg", "before_hw.jpg"), ("/tmp/ha_after_hw.jpg", "after_hw.jpg")]:
    try:
        blob = sftp.file(src, "rb").read()
        (OUT / dst).write_bytes(blob)
        print("saved", dst, len(blob))
    except Exception as e:
        print("missing", src, e)
sftp.close()
c.close()
raise SystemExit(code)
