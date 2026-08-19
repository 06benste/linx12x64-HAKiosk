#!/usr/bin/env python3
"""Rebuild atomisp-6.10/1.0.3-linx correctly and verify rear cam."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
# Ensure patch present
python3 /tmp/ha-rear/_patch_gmin_linx_csi_port_fix.py || true
grep -n LINX_CSI_PORT_FIX /usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c | head

KVER=$(uname -r)
systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true

# Correct DKMS package naming from dkms.conf
MOD=atomisp-6.10
VER=1.0.3-linx

# Repair dkms tree if broken from earlier wrong uninstall
mkdir -p /var/lib/dkms/$MOD/$VER
ln -sfn /usr/src/atomisp-6.10-1.0.3-linx /var/lib/dkms/$MOD/$VER/source || true
# Also keep legacy symlink name if tooling expects it
mkdir -p /var/lib/dkms/atomisp/6.10-1.0.3-linx || true

dkms remove -m $MOD -v $VER -k "$KVER" || true
dkms add -m $MOD -v $VER || true
dkms build -m $MOD -v $VER -k "$KVER"
dkms install -m $MOD -v $VER -k "$KVER" --force

echo '=== reload ==='
modprobe -r atomisp_gc2235 || true
modprobe -r atomisp || true
modprobe -r atomisp_gmin_platform || true
sleep 1
/opt/ha-kiosk/scripts/load-atomisp.sh
sleep 3

echo '=== dmesg ==='
dmesg | grep -iE 'LINX_CSI|gc2235|detected .*camera|port .*sensor|already has|camera pdata' | tail -n 50

echo '=== media ==='
media-ctl -p -d /dev/media0 2>&1 | head -n 90

echo '=== inputs ==='
v4l2-ctl -d /dev/video0 --list-inputs 2>&1 || true

if v4l2-ctl -d /dev/video0 --list-inputs 2>&1 | grep -q 'Input       : 1'; then
  echo '=== capture input1 ==='
  rm -f /tmp/cam_rear.raw /tmp/cam_rear.jpg
  timeout -s KILL 15 v4l2-ctl -d /dev/video0 --set-input=1 \
    --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
    --stream-mmap=3 --stream-count=10 --stream-to=/tmp/cam_rear.raw 2>&1 | tail -n 40 || true
  ls -la /tmp/cam_rear.raw || true
  if [[ -s /tmp/cam_rear.raw ]]; then
    ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -video_size 1600x1184 \
      -i /tmp/cam_rear.raw -vf 'crop=1584:1184:0:0,scale=800:600' -frames:v 1 /tmp/cam_rear.jpg
    ls -la /tmp/cam_rear.jpg
  fi
else
  echo 'NO_INPUT_1'
fi

systemctl start ha-kiosk-camera-stream.service || true
echo REAR_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-rear")
    except OSError:
        pass
    with sftp.file("/tmp/ha-rear/_patch_gmin_linx_csi_port_fix.py", "wb") as f:
        f.write((ROOT / "scripts/_patch_gmin_linx_csi_port_fix.py").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/rebuild_rear.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/rebuild_rear.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/rebuild_rear.sh", timeout=1200, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    sftp = c.open_sftp()
    try:
        blob = sftp.file("/tmp/cam_rear.jpg", "rb").read()
        (OUT / "rear.jpg").write_bytes(blob)
        print("saved rear.jpg", len(blob))
    except Exception as e:
        print("no rear jpg", e)
    sftp.close()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
