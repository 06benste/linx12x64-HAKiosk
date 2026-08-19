#!/usr/bin/env python3
"""Write MQTT credentials and restart bridge."""
from __future__ import annotations

import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"

MQTT_ENV = """MQTT_HOST=192.168.8.110
MQTT_PORT=1883
MQTT_USER=kioskuser
MQTT_PASSWORD=kiosk
MQTT_INTERVAL=15
"""

REMOTE = r"""#!/bin/bash
set -euxo pipefail
install -m 600 /tmp/mqtt.env /opt/ha-kiosk/mqtt.env
systemctl restart ha-kiosk-mqtt.service
sleep 3
systemctl is-active ha-kiosk-mqtt.service
journalctl -u ha-kiosk-mqtt.service -n 40 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = client.open_sftp()
    with sftp.file("/tmp/mqtt.env", "w") as f:
        f.write(MQTT_ENV.replace("\r\n", "\n"))
    with sftp.file("/tmp/set-mqtt.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/set-mqtt.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = client.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/set-mqtt.sh", timeout=60
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-2000:])
    code = stdout.channel.recv_exit_status()

    # Verify MQTT auth + discovery topic from PC
    time.sleep(2)
    try:
        import paho.mqtt.client as mqtt

        seen = {"conn": None, "disc": False}

        def on_connect(c, u, f, rc, props=None):
            seen["conn"] = int(getattr(rc, "value", rc))
            c.subscribe("homeassistant/+/hakiosk_tablet/#", qos=0)
            c.subscribe("hakiosk/#", qos=0)

        def on_message(c, u, msg):
            if msg.topic.startswith("homeassistant/") or msg.topic.startswith("hakiosk/"):
                seen["disc"] = True
                print("MQTT", msg.topic, msg.payload[:80])

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="verify-hakiosk")
        c.username_pw_set("kioskuser", "kiosk")
        c.on_connect = on_connect
        c.on_message = on_message
        c.connect("192.168.8.110", 1883, 30)
        c.loop_start()
        time.sleep(5)
        c.loop_stop()
        c.disconnect()
        print("mqtt_auth_rc", seen["conn"], "saw_topics", seen["disc"])
    except Exception as exc:
        print("mqtt verify failed", exc)

    client.close()
    sys.exit(0 if code == 0 else 1)


if __name__ == "__main__":
    main()
