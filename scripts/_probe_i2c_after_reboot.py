#!/usr/bin/env python3
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
CMD = r"""
set -euxo pipefail
modprobe i2c-dev || true
ls -l /dev/i2c-* || true
ls -l /sys/bus/i2c/devices/ | head -80
echo '=== GCTI ==='
ls -l /sys/bus/i2c/devices/i2c-GCTI2355:* 2>/dev/null || true
python3 - <<'PY'
from pathlib import Path
import subprocess
for d in sorted(Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*')):
    real=d.resolve()
    print('dev', d, '->', real)
    bus=None
    for p in str(real).split('/'):
        if p.startswith('i2c-') and p[4:].isdigit():
            bus=int(p[4:])
    print(' bus', bus)
    if bus is None: continue
    for addr in (0x3c, 0x3e, 0x20, 0x21, 0x36):
        r=subprocess.run(['i2cget','-y','-f',str(bus),hex(addr),'0xf0'], capture_output=True, text=True)
        print(' ', hex(addr), 'f0', r.stdout.strip() or r.stderr.strip()[:80])
# wake stream
import threading, time, urllib.request
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=20).read(2048)
  except Exception as e: print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(4)
print('--- after stream wake ---')
for d in sorted(Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*')):
    real=d.resolve(); bus=None
    for p in str(real).split('/'):
        if p.startswith('i2c-') and p[4:].isdigit(): bus=int(p[4:])
    if bus is None: continue
    subprocess.run(['i2cset','-y','-f',str(bus),'0x3c','0xfe','0x00'], capture_output=True)
    r=subprocess.run(['i2cget','-y','-f',str(bus),'0x3c','0xf0'], capture_output=True, text=True)
    print('bus', bus, 'id', r.stdout.strip(), r.stderr.strip()[:60])
    for reg in (0x03,0x04,0xb0,0xb6):
        rr=subprocess.run(['i2cget','-y','-f',str(bus),'0x3c',hex(reg)], capture_output=True, text=True)
        print(' ', hex(reg), rr.stdout.strip())
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/i2c_probe2.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/i2c_probe2.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/i2c_probe2.sh", timeout=90, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
