#!/usr/bin/env python3
"""Find what re-enables the display ~30s after blank."""
from __future__ import annotations

import sys
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
REMOTE = r"""
set -uo pipefail
echo '=== processes with xset/dpms/noblank ==='
ps auxww | grep -iE 'xset|noblank|dpms' | grep -v grep || true
echo
echo '=== crontab / systemd timers ==='
crontab -u kioskuser -l 2>/dev/null || true
systemctl list-timers --all --no-pager | head -40
echo
echo '=== kiosk launch / xinit snippets ==='
grep -nR -E 'xset|dpms|noblank|blank' /home/kioskuser /opt/ha-kiosk /etc/systemd/system 2>/dev/null | grep -v Binary | head -80
echo
echo '=== .xinitrc / .xsession / profile ==='
for f in /home/kioskuser/.xinitrc /home/kioskuser/.xsession /home/kioskuser/.profile /home/kioskuser/.bashrc /opt/ha-kiosk/scripts/*; do
  [[ -f "$f" ]] || continue
  if grep -qE 'xset|dpms|noblank' "$f" 2>/dev/null; then
    echo "--- $f ---"
    grep -nE 'xset|dpms|noblank|sleep' "$f" || true
  fi
done
echo
echo '=== getty/autologin scripts ==='
ls -la /home/kioskuser/.bash_profile /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
grep -nR . /etc/systemd/system/getty@tty1.service.d 2>/dev/null || true
"""

def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/find-noblank.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/find-noblank.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/find-noblank.sh", timeout=60, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    c.close()

if __name__ == "__main__":
    main()
