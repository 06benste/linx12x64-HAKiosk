#!/usr/bin/env python3
"""Deploy HW exposure keeper + optional DKMS gain patch after reboot."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)
DO_DKMS = "--dkms" in sys.argv

REMOTE = r"""
set -euxo pipefail
install -m 644 /tmp/ha-hw/gc2355_hw_exposure.py /opt/ha-kiosk/scripts/gc2355_hw_exposure.py
install -m 755 /tmp/ha-hw/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-hw/camera_preview.json /opt/ha-kiosk/config/camera_preview.json
install -m 644 /tmp/ha-hw/_patch_gc2355_tables.py /opt/ha-kiosk/scripts/_patch_gc2355_tables.py
install -m 644 /tmp/ha-hw/_patch_gc2355_set_exposure_again.py /opt/ha-kiosk/scripts/_patch_gc2355_set_exposure_again.py
install -m 644 /tmp/ha-hw/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service
modprobe i2c-dev || true
systemctl daemon-reload

DO_DKMS=__DO_DKMS__
if [[ "$DO_DKMS" == "1" ]]; then
  python3 /opt/ha-kiosk/scripts/_patch_gc2355_tables.py || true
  python3 /opt/ha-kiosk/scripts/_patch_gc2355_set_exposure_again.py || true
  # Mirror into both trees if present
  for src in /usr/src/atomisp-6.10-1.0.3-linx /usr/src/atomisp-dkms-src; do
    if [[ -f $src/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h ]]; then
      echo "tree $src"
    fi
  done
  dkms remove atomisp/6.10-1.0.3-linx -k $(uname -r) --all 2>/dev/null || true
  # Prefer install/build of existing module
  if [[ -d /usr/src/atomisp-6.10-1.0.3-linx ]]; then
    dkms build -m atomisp -v 6.10-1.0.3-linx -k $(uname -r) || dkms install -m atomisp -v 6.10-1.0.3-linx -k $(uname -r) || true
    dkms install -m atomisp -v 6.10-1.0.3-linx -k $(uname -r) || true
  fi
  systemctl stop ha-kiosk-camera-stream.service || true
  /opt/ha-kiosk/scripts/load-atomisp.sh || true
fi

systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 40); do
  curl -fsS --max-time 2 http://127.0.0.1:17824/health >/dev/null && break
  sleep 1
done
python3 - <<'PY'
import io, json, time, urllib.request, threading, subprocess, pathlib
from PIL import Image, ImageStat

def suck():
    try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=30).read(8192)
    except Exception as e: print('suck', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(8)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
print('health', h)
data = urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=20).read()
open('/tmp/ha_hw_final.jpg','wb').write(data)
im = Image.open(io.BytesIO(data)).convert('RGB')
st = ImageStat.Stat(im)
face = ImageStat.Stat(im.crop((150,80,520,480))).mean
print('mean', [round(x,1) for x in st.mean], 'face', [round(x,1) for x in face], 'bytes', len(data))

def iget(bus,reg):
    r=subprocess.run(['i2cget','-y','-f',str(bus),'0x3c',hex(reg)],capture_output=True,text=True)
    return None if r.returncode else int(r.stdout.strip(),16)
bus=None
for d in pathlib.Path('/sys/bus/i2c/devices').glob('i2c-GCTI2355:*'):
    for p in str(d.resolve()).split('/'):
        if p.startswith('i2c-') and p[4:].isdigit():
            bus=int(p[4:])
    subprocess.run(['i2cset','-y','-f',str(bus),'0x3c','0xfe','0x00'], capture_output=True)
    if bus is not None and iget(bus,0xf0) is not None:
        break
if bus is not None:
    exp=((iget(bus,0x03) or 0)<<8)|(iget(bus,0x04) or 0)
    print('regs exposure', exp, 'b6', iget(bus,0xb6), 'b0', iget(bus,0xb0), 'vb', ((iget(bus,0x07) or 0)<<8)|(iget(bus,0x08) or 0))
print(subprocess.getoutput('journalctl -u ha-kiosk-camera-stream.service -n 30 --no-pager | tail -n 30'))
PY
""".replace("__DO_DKMS__", "1" if DO_DKMS else "0")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("DO_DKMS", DO_DKMS)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-hw")
    except OSError:
        pass
    files = {
        "gc2355_hw_exposure.py": ROOT / "scripts" / "gc2355_hw_exposure.py",
        "camera-stream-server.py": ROOT / "scripts" / "camera-stream-server.py",
        "camera_preview.json": ROOT / "config" / "camera_preview.json",
        "_patch_gc2355_tables.py": ROOT / "scripts" / "_patch_gc2355_tables.py",
        "_patch_gc2355_set_exposure_again.py": ROOT / "scripts" / "_patch_gc2355_set_exposure_again.py",
        "ha-kiosk-camera-stream.service": ROOT / "scripts" / "ha-kiosk-camera-stream.service",
    }
    for name, src in files.items():
        with sftp.file(f"/tmp/ha-hw/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/deploy_hw2.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy_hw2.sh", 0o755)
    sftp.close()
    timeout = 900 if DO_DKMS else 180
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy_hw2.sh", timeout=timeout, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    try:
        blob = sftp.file("/tmp/ha_hw_final.jpg", "rb").read()
        (OUT / "graded.jpg").write_bytes(blob)
        print("saved", len(blob))
    except Exception as e:
        print("snap missing", e)
    sftp.close()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
