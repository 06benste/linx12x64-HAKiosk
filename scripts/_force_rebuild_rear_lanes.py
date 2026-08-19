#!/usr/bin/env python3
"""Force-rebuild atomisp with lanes fix; verify rear stream after reboot."""
from __future__ import annotations

import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -euxo pipefail
python3 /tmp/ha-rear/_patch_gmin_linx_csi_lanes.py || true
grep -n 'LINX_CSI_LANES_FIX\|LINX_CSI_PORT_FIX' \
  /usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c | head

# Show stream_on table currently in source
grep -n -A6 'gc2235_stream_on' \
  /usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/i2c/gc2235.h | head -n 40

KVER=$(uname -r)
systemctl stop ha-kiosk-camera-stream.service || true
# Force rebuild so lanes patch is compiled
dkms remove -m atomisp-6.10 -v 1.0.3-linx -k "$KVER" || true
dkms build -m atomisp-6.10 -v 1.0.3-linx -k "$KVER" --force
dkms install -m atomisp-6.10 -v 1.0.3-linx -k "$KVER" --force
echo REBOOTING
reboot
"""

VERIFY = r"""
set -euxo pipefail
sleep 5
echo '=== boot cam lines ==='
dmesg | grep -iE 'LINX_CSI|detected .*camera|camera pdata|sensor ID' | tail -n 30
systemctl stop ha-kiosk-camera-stream.service || true
sleep 1
pkill -9 -f 'v4l2-ctl --stream' || true
echo '=== inputs ==='
v4l2-ctl -d /dev/video0 --list-inputs
dmesg -C || true
echo '=== rear stream ==='
timeout -s KILL 20 v4l2-ctl -d /dev/video0 --set-input=1 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=3 --stream-count=8 --stream-to=/tmp/cam_rear.raw 2>&1 || true
ls -la /tmp/cam_rear.raw
dmesg | tail -n 50
if [[ -s /tmp/cam_rear.raw ]]; then
  python3 - <<'PY'
from pathlib import Path
raw=Path('/tmp/cam_rear.raw').read_bytes()
# AtomISP frame = 2842624
fs=2842624
print('bytes', len(raw), 'frames', len(raw)//fs)
# write first full frame
Path('/tmp/cam_rear_one.raw').write_bytes(raw[:fs])
PY
  ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -s 1600x1184 \
    -i /tmp/cam_rear_one.raw -vf 'crop=1584:1184:0:0,scale=640:480' -frames:v 1 /tmp/cam_rear.jpg
  ls -la /tmp/cam_rear.jpg
fi
v4l2-ctl -d /dev/video0 --set-input=0 || true
systemctl start ha-kiosk-camera-stream.service || true
"""


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-rear")
    except OSError:
        pass
    with sftp.file("/tmp/ha-rear/_patch_gmin_linx_csi_lanes.py", "wb") as f:
        f.write((ROOT / "scripts/_patch_gmin_linx_csi_lanes.py").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/force_rebuild.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/force_rebuild.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/force_rebuild.sh", timeout=900, get_pty=True)
    try:
        print(o.read().decode("utf-8", "replace"))
    except Exception as e:
        print("closed", e)
    try:
        c.close()
    except Exception:
        pass

    print("waiting reboot...")
    for i in range(40):
        time.sleep(5)
        try:
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username="kioskuser", password=PASS, timeout=10, allow_agent=False, look_for_keys=False)
            print("up", i)
            break
        except Exception:
            print("wait", i)
    else:
        raise SystemExit("no boot")

    sftp = c.open_sftp()
    with sftp.file("/tmp/verify_rear2.sh", "w") as f:
        f.write(VERIFY.replace("\r\n", "\n"))
    sftp.chmod("/tmp/verify_rear2.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/verify_rear2.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    sftp = c.open_sftp()
    try:
        blob = sftp.file("/tmp/cam_rear.jpg", "rb").read()
        (OUT / "rear.jpg").write_bytes(blob)
        print("saved rear.jpg", len(blob))
    except Exception as e:
        print("no jpg", e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
