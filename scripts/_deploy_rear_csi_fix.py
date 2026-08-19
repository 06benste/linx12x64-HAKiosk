#!/usr/bin/env python3
"""Apply CSI port fix, rebuild atomisp DKMS, reload, verify rear links."""
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
python3 /tmp/ha-rear/_patch_gmin_linx_csi_port_fix.py
# Also ensure hardcoded quirk exists (harmless if DMI unmatched)
python3 /opt/ha-kiosk/scripts/_patch_gmin_linx_quirk.py 2>/dev/null || python3 /tmp/ha-rear/_patch_gmin_linx_quirk.py || true

echo '=== rebuild dkms (may take several minutes) ==='
KVER=$(uname -r)
# Build/install linx atomisp package if present
if dkms status 2>/dev/null | grep -q atomisp; then
  dkms status
fi
# Force rebuild of the linx tree module
if [[ -d /usr/src/atomisp-6.10-1.0.3-linx ]]; then
  dkms uninstall -m atomisp -v 6.10-1.0.3-linx -k "$KVER" || true
  dkms build -m atomisp -v 6.10-1.0.3-linx -k "$KVER"
  dkms install -m atomisp -v 6.10-1.0.3-linx -k "$KVER" --force
else
  echo 'atomisp src tree missing' >&2
  exit 1
fi

systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true
sleep 1

echo '=== reload modules ==='
# unload dependents then atomisp stack
modprobe -r atomisp_gc2235 || true
modprobe -r atomisp || true
modprobe -r atomisp_gmin_platform || true
sleep 1
/opt/ha-kiosk/scripts/load-atomisp.sh
sleep 2

echo '=== dmesg after reload ==='
dmesg | grep -iE 'LINX_CSI|gc2235|detected .*camera|port .*sensor|already has|CsiPort' | tail -n 60

echo '=== media topology ==='
media-ctl -p -d /dev/media0 2>&1 | head -n 100

echo '=== inputs ==='
v4l2-ctl -d /dev/video0 --list-inputs 2>&1 || true

echo '=== capture rear (input 1) ==='
if v4l2-ctl -d /dev/video0 --list-inputs 2>&1 | grep -q 'Input       : 1'; then
  timeout -s KILL 12 v4l2-ctl -d /dev/video0 --set-input=1 \
    --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
    --stream-mmap=3 --stream-count=8 --stream-to=/tmp/cam_rear.raw 2>&1 | tail -n 30 || true
  ls -la /tmp/cam_rear.raw 2>/dev/null || true
  # Convert one frame to jpeg if we got data
  if [[ -s /tmp/cam_rear.raw ]]; then
    python3 - <<'PY'
import pathlib
raw = pathlib.Path('/tmp/cam_rear.raw').read_bytes()
frame = 1600*1184*3//2  # NV12 with stride? AtomISP uses 1600 stride, 1584x1184 active — use server geometry
# Use ffmpeg via pipe for first aligned frame if possible
print('raw_bytes', len(raw), 'frames_est', len(raw)/2842624)
PY
    ffmpeg -y -f rawvideo -pix_fmt nv12 -video_size 1600x1184 -i /tmp/cam_rear.raw \
      -vf 'crop=1584:1184:0:0,scale=800:600' -frames:v 1 /tmp/cam_rear.jpg 2>/tmp/rear_ff.err || true
    ls -la /tmp/cam_rear.jpg 2>/dev/null || cat /tmp/rear_ff.err | tail -n 30
  fi
else
  echo 'NO_INPUT_1 — rear still not registered with atomisp'
fi

systemctl start ha-kiosk-camera-stream.service || true
echo REAR_DEPLOY_DONE
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
    for name in (
        "_patch_gmin_linx_csi_port_fix.py",
        "_patch_gmin_linx_quirk.py",
    ):
        src = ROOT / "scripts" / name
        with sftp.file(f"/tmp/ha-rear/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
    # also copy quirk to expected path used in remote script fallback
    with sftp.file("/tmp/deploy_rear.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy_rear.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy_rear.sh", timeout=900, get_pty=True)
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
