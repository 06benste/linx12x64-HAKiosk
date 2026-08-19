#!/usr/bin/env python3
"""Deploy battery/power sensors to tablet API, MQTT, drawer."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

FILES = [
    (ROOT / "scripts" / "power-api.py", "/tmp/ha-pwr/power-api.py"),
    (ROOT / "scripts" / "ha-kiosk-mqtt.py", "/tmp/ha-pwr/ha-kiosk-mqtt.py"),
    (ROOT / "chromium-extension" / "power-drawer.js", "/tmp/ha-pwr/power-drawer.js"),
    (ROOT / "chromium-extension" / "manifest.json", "/tmp/ha-pwr/manifest.json"),
]

REMOTE = r"""#!/bin/bash
set -euxo pipefail
install -m 755 /tmp/ha-pwr/power-api.py /opt/ha-kiosk/scripts/power-api.py
install -m 755 /tmp/ha-pwr/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
cp -a /opt/ha-kiosk/chromium-extension/config.js /tmp/ha-config.js.bak 2>/dev/null || true
install -m 644 /tmp/ha-pwr/power-drawer.js /opt/ha-kiosk/chromium-extension/power-drawer.js
install -m 644 /tmp/ha-pwr/manifest.json /opt/ha-kiosk/chromium-extension/manifest.json
if [[ -f /tmp/ha-config.js.bak ]]; then mv /tmp/ha-config.js.bak /opt/ha-kiosk/chromium-extension/config.js; fi
chown -R kioskuser:kioskuser /opt/ha-kiosk
systemctl restart ha-kiosk-power.service ha-kiosk-mqtt.service
sleep 2
python3 - <<'PY'
import json, urllib.request
st=json.load(urllib.request.urlopen('http://127.0.0.1:17823/status', timeout=5))
print(json.dumps(st.get('power'), indent=2))
PY
journalctl -u ha-kiosk-mqtt.service -n 8 --no-pager
# Soft-reload drawer: restart display session
systemctl restart getty@tty1.service
echo OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-pwr")
    except OSError:
        pass
    for local, remote in FILES:
        with sftp.file(remote, "wb") as f:
            f.write(local.read_bytes().replace(b"\r\n", b"\n"))
        print("uploaded", local.name, flush=True)
    with sftp.file("/tmp/deploy-power.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-power.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-power.sh", timeout=90
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out)
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1500:])
    code = stdout.channel.recv_exit_status()

    time.sleep(3)
    try:
        import paho.mqtt.client as mqtt

        seen = []

        def on_connect(c, u, f, rc, props=None):
            c.subscribe("homeassistant/+/hakiosk_tablet/battery/#")
            c.subscribe("homeassistant/+/hakiosk_tablet/plugged_in/#")
            c.subscribe("hakiosk/hakiosk_tablet/battery")
            c.subscribe("hakiosk/hakiosk_tablet/plugged_in")

        def on_message(c, u, msg):
            seen.append((msg.topic, msg.payload[:60]))

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="batt-check")
        c.username_pw_set("kioskuser", "kiosk")
        c.on_connect = on_connect
        c.on_message = on_message
        c.connect("192.168.8.110", 1883, 30)
        c.loop_start()
        time.sleep(5)
        c.loop_stop()
        c.disconnect()
        print("mqtt samples:", seen[:8])
    except Exception as exc:
        print("mqtt check", exc)

    client.close()
    sys.exit(0 if code == 0 and "OK" in out else 1)


if __name__ == "__main__":
    main()
