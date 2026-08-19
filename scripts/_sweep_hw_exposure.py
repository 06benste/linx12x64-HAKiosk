#!/usr/bin/env python3
"""Sweep GC2355 HW exposure/gain; mild software look for fair compare."""
from __future__ import annotations

import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

# Mild software grade so HW differences show clearly
SOFT = {
    "exposure_ev": 0.35,
    "contrast": 1.02,
    "saturation": 1.05,
    "wb_r": 1.45,
    "wb_g": 0.82,
    "wb_b": 1.05,
    "shadows": 0.18,
    "highlights": 0.12,
}

# (name, exp_h, exp_l, vb_h, vb_l, b0, b1, b2, b6)
PROFILES = [
    ("base_stock", 0x04, 0x5F, 0x00, 0x0B, 0x50, 0x02, 0x40, 0x00),
    ("gain2", 0x04, 0x5F, 0x00, 0x0B, 0x50, 0x02, 0x40, 0x02),
    ("gain4", 0x04, 0x5F, 0x00, 0x0B, 0x55, 0x03, 0x40, 0x04),
    ("exp16_g3", 0x06, 0x40, 0x00, 0x80, 0x55, 0x03, 0x40, 0x03),
    ("exp18_g4", 0x07, 0x20, 0x01, 0x00, 0x58, 0x03, 0x80, 0x04),
    ("exp20_g5", 0x07, 0xE0, 0x01, 0x40, 0x60, 0x04, 0x00, 0x05),
]

REMOTE = r"""
set -euxo pipefail
modprobe i2c-dev || true
systemctl start ha-kiosk-camera-stream.service || true

python3 - <<'PY'
import io, json, time, urllib.request, threading, subprocess
from pathlib import Path
from PIL import Image, ImageStat

SOFT = __SOFT__
PROFILES = __PROFILES__
ADDR = 0x3c

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def iget(bus, reg):
    r = run(['i2cget','-y','-f',str(bus),hex(ADDR),hex(reg)])
    return None if r.returncode else int(r.stdout.strip(), 16)

def iset(bus, reg, val):
    return run(['i2cset','-y','-f',str(bus),hex(ADDR),hex(reg),hex(val)]).returncode == 0

def page0(bus):
    iset(bus, 0xfe, 0x00)

def find_bus():
    for d in sorted(Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*')):
        bus=None
        for p in str(d.resolve()).split('/'):
            if p.startswith('i2c-') and p[4:].isdigit():
                bus=int(p[4:])
        if bus is None: continue
        page0(bus)
        if iget(bus, 0xf0) is not None:
            return bus
    raise SystemExit('no sensor bus')

def apply(bus, p):
    name, eh, el, vbh, vbl, b0, b1, b2, b6 = p
    page0(bus)
    iset(bus, 0x07, vbh); iset(bus, 0x08, vbl)
    iset(bus, 0x03, eh); iset(bus, 0x04, el)
    iset(bus, 0xb0, b0); iset(bus, 0xb1, b1); iset(bus, 0xb2, b2); iset(bus, 0xb6, b6)
    time.sleep(0.8)
    exp = ((iget(bus,0x03) or 0)<<8) | (iget(bus,0x04) or 0)
    vbh2, vbl2, b6v = iget(bus,0x07), iget(bus,0x08), iget(bus,0xb6)
    print(f'applied {name} exp={exp} b6={b6v} vb={vbh2}/{vbl2}')

def wake():
    def suck():
        try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(2048)
        except Exception: pass
    threading.Thread(target=suck, daemon=True).start()

# Set mild software look once
body = json.dumps({'software_preview': SOFT}).encode()
req = urllib.request.Request('http://127.0.0.1:17824/api/look', data=body, headers={'Content-Type':'application/json'}, method='POST')
print('soft', urllib.request.urlopen(req, timeout=45).read().decode())
time.sleep(3)
wake(); time.sleep(2)

bus = find_bus()
results = []
for p in PROFILES:
    name = p[0]
    apply(bus, p)
    wake(); time.sleep(2.5)
    data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
    path = f'/tmp/hw_{name}.jpg'
    open(path,'wb').write(data)
    im = Image.open(io.BytesIO(data)).convert('RGB')
    st = ImageStat.Stat(im)
    face = ImageStat.Stat(im.crop((150,80,520,480))).mean
    mean = [round(x,1) for x in st.mean]
    fmean = [round(x,1) for x in face]
    print(f'SNAP {name} mean={mean} face={fmean} bytes={len(data)}')
    results.append((name, mean, fmean, len(data)))

print('SUMMARY')
for row in results:
    print(row)
PY
""".replace("__SOFT__", repr(SOFT)).replace("__PROFILES__", repr(PROFILES))

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/sweep_hw.sh", "w") as f:
    f.write(REMOTE)
sftp.chmod("/tmp/sweep_hw.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/sweep_hw.sh", timeout=180, get_pty=True)
print(o.read().decode("utf-8", "replace"))
sftp = c.open_sftp()
for name, *_ in PROFILES:
    src = f"/tmp/hw_{name}.jpg"
    try:
        blob = sftp.file(src, "rb").read()
        (OUT / f"hw_{name}.jpg").write_bytes(blob)
        print("saved", name, len(blob))
    except Exception as e:
        print("miss", name, e)
sftp.close()
c.close()
