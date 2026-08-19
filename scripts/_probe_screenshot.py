#!/usr/bin/env python3
"""Check which screenshot tools are available on the tablet."""
from __future__ import annotations
import sys
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
REMOTE = r"""
set -uo pipefail
for c in import scrot gnome-screenshot ffmpeg xwd convert; do
  echo -n "$c: "; command -v $c || echo missing
done
echo '=== try import ==='
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority \
  import -window root -quality 70 /tmp/ha-screen-test.jpg 2>&1 || true
ls -la /tmp/ha-screen-test.jpg 2>/dev/null || true
file /tmp/ha-screen-test.jpg 2>/dev/null || true
echo '=== try ffmpeg x11grab ==='
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority \
  ffmpeg -y -f x11grab -video_size 1920x1080 -i :0.0 -frames:v 1 -q:v 5 /tmp/ha-screen-ff.jpg 2>&1 | tail -20
ls -la /tmp/ha-screen-ff.jpg 2>/dev/null || true
"""

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/probe-shot.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/probe-shot.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/probe-shot.sh", timeout=60, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    c.close()

if __name__ == "__main__":
    main()
