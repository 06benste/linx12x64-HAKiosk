#!/usr/bin/env python3
"""Deploy expanded kiosk control drawer to hakiosk."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "scripts" / "power-api.py", "/tmp/ha-ext/power-api.py"),
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-ext/manifest.json"),
    (ROOT / "chromium-extension" / "background.js", "/tmp/ha-ext/background.js"),
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-ext/power-drawer.js"),
    (ROOT / "chromium-extension" / "kiosk-mode.js", "/tmp/ha-ext/kiosk-mode.js"),
    (ROOT / "chromium-extension" / "content.js", "/tmp/ha-ext/content.js"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
# Optional volume control support
apt-get install -y --no-install-recommends alsa-utils 2>/dev/null || true

install -d -m 755 /opt/ha-kiosk/chromium-extension /opt/ha-kiosk/scripts
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 755 /tmp/ha-ext/power-api.py /opt/ha-kiosk/scripts/power-api.py
install -m 644 /tmp/ha-ext/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
install -m 644 /tmp/ha-ext/background.js /opt/ha-kiosk/chromium-extension/background.js
install -m 644 /tmp/ha-ext/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 644 /tmp/ha-ext/kiosk-mode.js /opt/ha-kiosk/chromium-extension/kiosk-mode.js
install -m 644 /tmp/ha-ext/content.js /opt/ha-kiosk/chromium-extension/content.js
if [[ -f /tmp/ha-config.js.bak ]]; then
  mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js
fi
chown -R kioskuser:kioskuser /opt/ha-kiosk

# Allow root power-api to write backlight; already root via systemd
systemctl restart ha-kiosk-power.service
sleep 1
python3 - <<'PY'
import urllib.request, json
print(urllib.request.urlopen('http://127.0.0.1:17823/status', timeout=5).read().decode()[:500])
PY
systemctl restart getty@tty1.service
echo DEPLOY_OK
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
    with sftp.file("/tmp/deploy-drawer2.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-drawer2.sh", 0o755)
    sftp.close()

    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-drawer2.sh", timeout=180
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out[-4000:])
    lines = [l for l in err.splitlines() if "password" not in l.lower()]
    if lines:
        print("STDERR:\n" + "\n".join(lines)[-2500:])
    print("exit", code)
    client.close()
    if code != 0 or "DEPLOY_OK" not in out:
        sys.exit(1)


if __name__ == "__main__":
    main()
