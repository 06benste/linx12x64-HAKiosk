#!/usr/bin/env python3
"""Deploy screen screenshot MQTT camera and verify first frame."""
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 755 /tmp/ha-shot/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
ENV=/opt/ha-kiosk/mqtt.env
if [[ -f "$ENV" ]]; then
  grep -q '^SCREENSHOT_ENABLED=' "$ENV" || echo 'SCREENSHOT_ENABLED=1' >> "$ENV"
  grep -q '^SCREENSHOT_INTERVAL=' "$ENV" || echo 'SCREENSHOT_INTERVAL=30' >> "$ENV"
  grep -q '^SCREENSHOT_WIDTH=' "$ENV" || echo 'SCREENSHOT_WIDTH=960' >> "$ENV"
fi
systemctl restart ha-kiosk-mqtt.service
sleep 3
systemctl is-active ha-kiosk-mqtt.service
journalctl -u ha-kiosk-mqtt.service -n 20 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-shot")
    except OSError:
        pass
    data = (ROOT / "scripts" / "ha-kiosk-mqtt.py").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/ha-shot/ha-kiosk-mqtt.py", "wb") as f:
        f.write(data)
    with sftp.file("/tmp/deploy-shot.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-shot.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-shot.sh",
        timeout=90,
        get_pty=True,
    )
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    if stdout.channel.recv_exit_status() != 0:
        raise SystemExit(1)

    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' cat /opt/ha-kiosk/mqtt.env", timeout=20, get_pty=True)
    env: dict[str, str] = {}
    for line in o.read().decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

    import paho.mqtt.client as mqtt

    seen = {"cfg": False, "bytes": 0}

    def on_message(_cli, _u, msg):
        if msg.topic.endswith("/screen/config") and msg.payload:
            seen["cfg"] = True
        elif msg.topic.endswith("/screen_shot") and not msg.topic.endswith("attr"):
            seen["bytes"] = len(msg.payload)

    cli = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="verify-screen-shot",
        protocol=mqtt.MQTTv311,
    )
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    cli.subscribe("homeassistant/camera/hakiosk_tablet/screen/config")
    cli.subscribe("hakiosk/hakiosk_tablet/screen_shot")
    cli.loop_start()
    for i in range(40):
        if seen["cfg"] and seen["bytes"] > 1000:
            break
        time.sleep(0.5)
        if i in (10, 20, 30):
            print(f"… waiting shot cfg={seen['cfg']} bytes={seen['bytes']}", flush=True)
    cli.loop_stop()
    cli.disconnect()
    c.close()
    print(f"discovery={seen['cfg']} jpeg_bytes={seen['bytes']}", flush=True)
    if not seen["cfg"] or seen["bytes"] < 1000:
        raise SystemExit("screenshot camera not ready")
    print("OK", flush=True)


if __name__ == "__main__":
    main()
