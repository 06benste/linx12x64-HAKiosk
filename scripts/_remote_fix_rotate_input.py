#!/usr/bin/env python3
"""Install xinput, fix rotate remapping, reset screen to normal."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends xinput
install -m 755 /tmp/power-api.py /opt/ha-kiosk/scripts/power-api.py
systemctl restart ha-kiosk-power.service
sleep 1

# Immediately restore usable landscape + remap touch
export DISPLAY=:0
export XAUTHORITY=/home/kioskuser/.Xauthority
OUT=$(xrandr --current | awk '/ connected/{print $1; exit}')
xrandr --output "$OUT" --rotate normal
# Remap all pointer devices
while read -r line; do
  echo "$line" | grep -q XTEST && continue
  echo "$line" | grep -Eq 'pointer|touch|Touch|ABS' || continue
  id=$(echo "$line" | sed -n 's/.*id=\([0-9]\+\).*/\1/p')
  [ -n "$id" ] || continue
  xinput map-to-output "$id" "$OUT" || true
done < <(xinput list)

# Also force identity matrix on anything with CTM
while read -r id; do
  [ -n "$id" ] || continue
  xinput list-props "$id" 2>/dev/null | grep -q 'Coordinate Transformation Matrix' || continue
  xinput set-prop "$id" 'Coordinate Transformation Matrix' 1 0 0 0 1 0 0 0 1 || true
  xinput map-to-output "$id" "$OUT" || true
done < <(xinput list | sed -n 's/.*id=\([0-9]\+\).*/\1/p')

echo '--- devices ---'
xinput list
echo '--- rotation ---'
xrandr --current | head -n 3

# Resize chromium
wid=$(xdotool search --onlyvisible --class chromium | head -n1 || true)
if [ -n "$wid" ]; then
  xdotool windowmove "$wid" 0 0
  xdotool windowsize "$wid" 1920 1080
fi

python3 - <<'PY'
import json, urllib.request
req=urllib.request.Request('http://127.0.0.1:17823/rotate', data=b'{"direction":"normal"}', headers={'Content-Type':'application/json'}, method='POST')
print(urllib.request.urlopen(req, timeout=8).read().decode())
PY
echo FIX_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    data = (ROOT / "scripts" / "power-api.py").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/power-api.py", "wb") as f:
        f.write(data)
    with sftp.file("/tmp/fix-rotate.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-rotate.sh", 0o755)
    sftp.close()
    # Run as root but X commands need the user env — script sets DISPLAY/XAUTHORITY
    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/fix-rotate.sh", timeout=120
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out[-5000:])
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-3000:])
    code = stdout.channel.recv_exit_status()
    print("exit", code)
    client.close()
    sys.exit(0 if code == 0 and "FIX_OK" in out else 1)


if __name__ == "__main__":
    main()
