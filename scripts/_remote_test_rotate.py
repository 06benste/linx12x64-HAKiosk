#!/usr/bin/env python3
import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

SCRIPT = r"""#!/bin/bash
set -euxo pipefail
install -m 755 /tmp/power-api.py /opt/ha-kiosk/scripts/power-api.py
systemctl restart ha-kiosk-power.service
sleep 1
python3 - <<'PY'
import json, urllib.request

def post(d):
    req = urllib.request.Request(
        'http://127.0.0.1:17823/rotate',
        data=json.dumps(d).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    return json.load(urllib.request.urlopen(req, timeout=10))

print('left', post({'direction': 'left'}))
print('normal', post({'direction': 'normal'}))
PY
export DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority
echo 'CTM touch:'
xinput list-props 15 | grep -i 'Coordinate Transformation Matrix' || true
xrandr --current | head -n 2
echo OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    with sftp.file("/tmp/power-api.py", "wb") as f:
        f.write((ROOT / "scripts" / "power-api.py").read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/test-rotate.sh", "w") as f:
        f.write(SCRIPT.replace("\r\n", "\n"))
    sftp.chmod("/tmp/test-rotate.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = client.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/test-rotate.sh", timeout=60)
    print(stdout.read().decode())
    print("STDERR:", "\n".join(l for l in stderr.read().decode().splitlines() if "password" not in l.lower())[-2000:])
    code = stdout.channel.recv_exit_status()
    print("exit", code)
    client.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
