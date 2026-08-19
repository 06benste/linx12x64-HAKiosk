#!/usr/bin/env python3
"""Deploy power drawer to hakiosk and restart kiosk session."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
USER = "kioskuser"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-ext/manifest.json"),
    (ROOT / "chromium-extension" / "background.js", "/tmp/ha-ext/background.js"),
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-ext/power-drawer.js"),
    (ROOT / "chromium-extension" / "content.js", "/tmp/ha-ext/content.js"),
    (ROOT / "scripts" / "power-api.py", "/tmp/ha-ext/power-api.py"),
    (ROOT / "scripts" / "ha-kiosk-power.service", "/tmp/ha-ext/ha-kiosk-power.service"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
install -d -m 755 /opt/ha-kiosk/chromium-extension /opt/ha-kiosk/scripts
# Keep existing config.js credentials
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 644 /tmp/ha-ext/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
install -m 644 /tmp/ha-ext/background.js /opt/ha-kiosk/chromium-extension/background.js
install -m 644 /tmp/ha-ext/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 644 /tmp/ha-ext/content.js /opt/ha-kiosk/chromium-extension/content.js
if [[ -f /tmp/ha-config.js.bak ]]; then
  mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js
fi
install -m 755 /tmp/ha-ext/power-api.py /opt/ha-kiosk/scripts/power-api.py
install -m 644 /tmp/ha-ext/ha-kiosk-power.service /etc/systemd/system/ha-kiosk-power.service
chown -R kioskuser:kioskuser /opt/ha-kiosk
# Force Chromium to reload unpacked extension by touching profile Preferences lightly via restart
systemctl daemon-reload
systemctl enable --now ha-kiosk-power.service
sleep 1
curl -fsS http://127.0.0.1:17823/health
systemctl restart getty@tty1.service
echo DEPLOY_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASS, timeout=20, allow_agent=False, look_for_keys=False)

    sftp = client.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-ext")
    except OSError:
        pass
    for local, remote in FILES:
        data = local.read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(remote, "wb") as f:
            f.write(data)
        print(f"uploaded {local.name}", flush=True)
    with sftp.file("/tmp/deploy-power.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-power.sh", 0o755)
    sftp.close()

    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-power.sh", timeout=120
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out)
    lines = [l for l in err.splitlines() if "password" not in l.lower()]
    if lines:
        print("STDERR:\n" + "\n".join(lines)[-2500:])
    print("exit:", code)
    if code != 0 or "DEPLOY_OK" not in out:
        client.close()
        sys.exit(1)

    print("waiting for kiosk...", flush=True)
    time.sleep(18)
    stdin, stdout, stderr = client.exec_command(
        "systemctl is-active ha-kiosk-power.service; "
        "curl -fsS http://127.0.0.1:17823/health; echo; "
        "ps aux | grep -E 'chromium|openbox|power-api' | grep -v grep | head -n 8",
        timeout=30,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    client.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
