#!/usr/bin/env python3
"""List V4L2 controls / exposure / WB on the tablet camera."""
from __future__ import annotations

import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
REMOTE = r"""
set -uo pipefail
echo '=== v4l2-ctl --list-ctrls ==='
# may be busy; try briefly stopping stream client contention
v4l2-ctl -d /dev/video0 --list-ctrls 2>&1 || true
echo
echo '=== list-ctrls-menus ==='
v4l2-ctl -d /dev/video0 --list-ctrls-menus 2>&1 | head -120 || true
echo
echo '=== all extended ==='
v4l2-ctl -d /dev/video0 --all 2>&1 | grep -iE 'exposure|gain|white|balance|bright|contrast|saturat|hue|auto|backlight|power' || true
echo
echo '=== subdevs ==='
ls -la /dev/v4l-subdev* 2>/dev/null || true
for s in /dev/v4l-subdev*; do
  [[ -e "$s" ]] || continue
  echo "--- $s ---"
  v4l2-ctl -d "$s" --list-ctrls 2>&1 | head -40 || true
done
echo
echo '=== media entities ==='
media-ctl -d /dev/media0 -p 2>&1 | head -80 || true
"""

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/probe-ae.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/probe-ae.sh", 0o755)
    sftp.close()
    # Stop stream briefly so device isn't busy
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash -lc "
        f"'systemctl stop ha-kiosk-camera-stream.service; sleep 1; bash /tmp/probe-ae.sh; "
        f"systemctl start ha-kiosk-camera-stream.service'",
        timeout=90,
        get_pty=True,
    )
    print(o.read().decode("utf-8", "replace"))
    c.close()

if __name__ == "__main__":
    main()
