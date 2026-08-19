#!/usr/bin/env python3
"""Deploy blank-sticky display fix (keep-awake respects intentional blank)."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

XINITRC = """#!/bin/sh
# Keep-awake respects /opt/ha-kiosk/config/display_blanked (intentional blank).
rm -f /opt/ha-kiosk/config/display_blanked
/opt/ha-kiosk/scripts/keep-awake-x11.sh &
command -v openbox >/dev/null && openbox &
sleep 0.5
exec /opt/ha-kiosk/scripts/kiosk-x11.sh
"""

REMOTE = r"""
set -euxo pipefail
install -d -m 755 /opt/ha-kiosk/scripts /opt/ha-kiosk/config
install -m 755 /tmp/ha-blank/keep-awake-x11.sh /opt/ha-kiosk/scripts/keep-awake-x11.sh
install -m 755 /tmp/ha-blank/power-api.py /opt/ha-kiosk/scripts/power-api.py
install -m 755 /tmp/ha-blank/xinitrc /home/kioskuser/.xinitrc
chown kioskuser:kioskuser /home/kioskuser/.xinitrc
rm -f /opt/ha-kiosk/config/display_blanked

# Stop old keep-awake / inline xset loops (the sleep 30 / sleep 60 children).
pkill -u kioskuser -f 'keep-awake-x11.sh' 2>/dev/null || true
# Kill the legacy inline loop from .xinitrc: `while true; do xset ...; sleep 30`
ps -u kioskuser -o pid=,cmd= | while read -r pid cmd; do
  case "$cmd" in
    *'xset -dpms'*|*'sleep 30'*|*'sleep 60'*)
      # only kill shells clearly in the keep-awake pattern
      if echo "$cmd" | grep -qE 'while true|keep-awake|xset s off'; then
        kill "$pid" 2>/dev/null || true
      fi
      ;;
  esac
done
# Broader: any sleep 30 owned by a bash started for xset keep-alive
pkill -u kioskuser -f 'while true; do xset' 2>/dev/null || true
sleep 1

# Start the new keep-awake in the existing X session
runuser -u kioskuser -- env DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority \
  /bin/sh -c 'nohup /opt/ha-kiosk/scripts/keep-awake-x11.sh >/tmp/keep-awake-x11.log 2>&1 &'

systemctl restart ha-kiosk-power.service
sleep 2
systemctl is-active ha-kiosk-power.service
pgrep -af keep-awake-x11 || true
curl -fsS http://127.0.0.1:17823/status | python3 -c 'import sys,json; print(json.load(sys.stdin).get("display"))'
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-blank")
    except OSError:
        pass
    files = {
        "keep-awake-x11.sh": (ROOT / "scripts" / "keep-awake-x11.sh").read_bytes(),
        "power-api.py": (ROOT / "scripts" / "power-api.py").read_bytes(),
        "xinitrc": XINITRC.encode(),
    }
    for name, data in files.items():
        with sftp.file(f"/tmp/ha-blank/{name}", "wb") as f:
            f.write(data.replace(b"\r\n", b"\n"))
        print("uploaded", name, flush=True)
    with sftp.file("/tmp/deploy-blank-sticky.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-blank-sticky.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-blank-sticky.sh",
        timeout=90,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    if stdout.channel.recv_exit_status() != 0:
        raise SystemExit(1)

    def api(path: str) -> str:
        _, o, _ = c.exec_command(
            f"echo {PASS} | sudo -S -p '' curl -fsS -X POST http://127.0.0.1:17823{path}",
            timeout=20,
            get_pty=True,
        )
        return o.read().decode("utf-8", "replace")

    def status() -> str:
        _, o, _ = c.exec_command(
            f"echo {PASS} | sudo -S -p '' curl -fsS http://127.0.0.1:17823/status",
            timeout=20,
            get_pty=True,
        )
        import json

        raw = o.read().decode("utf-8", "replace")
        # strip sudo noise
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line).get("display", {})
        return {"raw": raw}

    print("=== blank ===", flush=True)
    print(api("/display-off"), flush=True)
    d = status()
    print("t0", d, flush=True)
    print("=== wait 40s (old bug woke at ~30s) ===", flush=True)
    time.sleep(40)
    d = status()
    print("t40", d, flush=True)
    if not (isinstance(d, dict) and d.get("state") == "blanked"):
        raise SystemExit("FAILED: screen woke by itself within 40s")
    print("=== wake ===", flush=True)
    print(api("/display-on"), flush=True)
    d = status()
    print("after wake", d, flush=True)
    if not (isinstance(d, dict) and d.get("state") == "on"):
        raise SystemExit("FAILED: wake did not restore on")
    c.close()
    print("OK — blank stays until wake", flush=True)


if __name__ == "__main__":
    main()
