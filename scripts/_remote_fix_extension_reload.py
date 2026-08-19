#!/usr/bin/env python3
"""Force-reload kiosk extension (fixes stale service worker)."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

# Bump so Chromium treats it as a new extension load
manifest = (ROOT / "chromium-extension" / "manifest.json").read_text(encoding="utf-8")
manifest = manifest.replace('"version": "1.3.0"', '"version": "1.3.1"')
(ROOT / "chromium-extension" / "manifest.json").write_text(manifest, encoding="utf-8")

FILES = [
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-ext/manifest.json"),
    (ROOT / "chromium-extension" / "background.js", "/tmp/ha-ext/background.js"),
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-ext/power-drawer.js"),
    (ROOT / "scripts" / "power-api.py", "/tmp/ha-ext/power-api.py"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
install -d /opt/ha-kiosk/chromium-extension
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 644 /tmp/ha-ext/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
install -m 644 /tmp/ha-ext/background.js /opt/ha-kiosk/chromium-extension/background.js
install -m 644 /tmp/ha-ext/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 755 /tmp/ha-ext/power-api.py /opt/ha-kiosk/scripts/power-api.py
if [[ -f /tmp/ha-config.js.bak ]]; then mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js; fi
chown -R kioskuser:kioskuser /opt/ha-kiosk

echo '--- background on disk ---'
head -n 5 /opt/ha-kiosk/chromium-extension/background.js
python3 -c "import json; print('ver', json.load(open('/opt/ha-kiosk/chromium-extension/manifest.json'))['version'])"

systemctl restart ha-kiosk-power.service
# Hard recycle Chromium so MV3 service worker reloads
systemctl stop getty@tty1.service || true
pkill -u kioskuser -9 chromium || true
pkill -u kioskuser -9 chrome || true
sleep 1
# Drop extension service worker cache bits if present
rm -rf /opt/ha-kiosk/chromium-profile/Default/Service\ Worker/CacheStorage || true
rm -rf /opt/ha-kiosk/chromium-profile/Default/Service\ Worker/ScriptCache || true
rm -f /opt/ha-kiosk/chromium-profile/Default/Network\ Persistent\ State || true
systemctl start getty@tty1.service

python3 - <<'PY'
import json, urllib.request
print('api status', json.load(urllib.request.urlopen('http://127.0.0.1:17823/status', timeout=5))['hostname'])
req=urllib.request.Request('http://127.0.0.1:17823/brightness', data=b'{"delta":0}', headers={'Content-Type':'application/json'}, method='POST')
print('api brightness', urllib.request.urlopen(req, timeout=5).read().decode())
PY
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
        print("uploaded", local.name)
    with sftp.file("/tmp/fix-ext.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-ext.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = client.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/fix-ext.sh", timeout=90)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-2000:])
    code = stdout.channel.recv_exit_status()
    print("exit", code)
    client.close()
    sys.exit(0 if code == 0 and "FIX_OK" in out else 1)


if __name__ == "__main__":
    main()
