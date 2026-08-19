#!/usr/bin/env python3
"""Enable HA kiosk-mode (?kiosk) on the tablet panel."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = "http://192.168.8.110:8123/dashboard-kiosk?kiosk"

FILES = [
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-ext/manifest.json"),
    (ROOT / "chromium-extension" / "kiosk-mode.js", "/tmp/ha-ext/kiosk-mode.js"),
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-ext/power-drawer.js"),
    (ROOT / "chromium-extension" / "background.js", "/tmp/ha-ext/background.js"),
    (ROOT / "chromium-extension" / "content.js", "/tmp/ha-ext/content.js"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
echo 'http://192.168.8.110:8123/dashboard-kiosk?kiosk' > /opt/ha-kiosk/url
install -d -m 755 /opt/ha-kiosk/chromium-extension
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 644 /tmp/ha-ext/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
install -m 644 /tmp/ha-ext/kiosk-mode.js /opt/ha-kiosk/chromium-extension/kiosk-mode.js
install -m 644 /tmp/ha-ext/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 644 /tmp/ha-ext/background.js /opt/ha-kiosk/chromium-extension/background.js
install -m 644 /tmp/ha-ext/content.js /opt/ha-kiosk/chromium-extension/content.js
if [[ -f /tmp/ha-config.js.bak ]]; then
  mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js
fi
chown -R kioskuser:kioskuser /opt/ha-kiosk
systemctl restart getty@tty1.service
echo DEPLOY_OK
cat /opt/ha-kiosk/url
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
        data = local.read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(remote, "wb") as f:
            f.write(data)
        print("uploaded", local.name, flush=True)
    with sftp.file("/tmp/enable-kiosk-mode.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/enable-kiosk-mode.sh", 0o755)
    sftp.close()

    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/enable-kiosk-mode.sh", timeout=60
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    lines = [l for l in err.splitlines() if "password" not in l.lower()]
    if lines:
        print("STDERR:\n" + "\n".join(lines)[-1500:])
    print("exit", code)
    client.close()
    if code != 0 or "DEPLOY_OK" not in out:
        sys.exit(1)
    print("URL set to", URL)


if __name__ == "__main__":
    main()
