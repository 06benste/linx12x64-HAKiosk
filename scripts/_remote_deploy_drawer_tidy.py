#!/usr/bin/env python3
"""Deploy tidied drawer + kiosk-mode sidebar hide."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-ui/power-drawer.js"),
    (ROOT / "chromium-extension" / "kiosk-mode.js", "/tmp/ha-ui/kiosk-mode.js"),
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-ui/manifest.json"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 644 /tmp/ha-ui/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 644 /tmp/ha-ui/kiosk-mode.js /opt/ha-kiosk/chromium-extension/kiosk-mode.js
install -m 644 /tmp/ha-ui/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
if [[ -f /tmp/ha-config.js.bak ]]; then mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js; fi
chown -R kioskuser:kioskuser /opt/ha-kiosk/chromium-extension
systemctl restart getty@tty1.service
echo OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-ui")
    except OSError:
        pass
    for local, remote in FILES:
        with sftp.file(remote, "wb") as f:
            f.write(local.read_bytes().replace(b"\r\n", b"\n"))
        print("uploaded", local.name)
    with sftp.file("/tmp/deploy-ui.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-ui.sh", 0o755)
    sftp.close()
    _, stdout, stderr = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-ui.sh", timeout=60)
    print(stdout.read().decode())
    err = stderr.read().decode()
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-800:])
    code = stdout.channel.recv_exit_status()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
