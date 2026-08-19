#!/usr/bin/env python3
"""Deploy direct-fetch drawer (no service worker)."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-ext/manifest.json"),
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-ext/power-drawer.js"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
install -d /opt/ha-kiosk/chromium-extension
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 644 /tmp/ha-ext/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
install -m 644 /tmp/ha-ext/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
rm -f /opt/ha-kiosk/chromium-extension/background.js
if [[ -f /tmp/ha-config.js.bak ]]; then mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js; fi
chown -R kioskuser:kioskuser /opt/ha-kiosk
python3 -c "import json; print(json.load(open('/opt/ha-kiosk/chromium-extension/manifest.json'))['version'])"
systemctl stop getty@tty1.service || true
pkill -u kioskuser -9 chromium || true
sleep 1
rm -rf '/opt/ha-kiosk/chromium-profile/Default/Service Worker' || true
systemctl start getty@tty1.service
echo FIX_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-ext")
    except OSError:
        pass
    for local, remote in FILES:
        with sftp.file(remote, "wb") as f:
            f.write(local.read_bytes().replace(b"\r\n", b"\n"))
        print("uploaded", local.name, flush=True)
    with sftp.file("/tmp/fix-direct.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-direct.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/fix-direct.sh", timeout=60
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1500:])
    code = stdout.channel.recv_exit_status()
    print("exit", code)
    client.close()
    if code != 0 or "FIX_OK" not in out:
        sys.exit(1)


if __name__ == "__main__":
    main()
