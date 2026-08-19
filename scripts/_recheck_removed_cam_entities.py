#!/usr/bin/env python3
from __future__ import annotations

import sys
import time

import paramiko
import paho.mqtt.client as mqtt

HOST = "192.168.8.201"
PASS = "kiosk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' cat /opt/ha-kiosk/mqtt.env", timeout=20, get_pty=True)
    env: dict[str, str] = {}
    for line in o.read().decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    seen: dict[str, bytes] = {}

    def on_m(_cli, _u, msg):
        seen[msg.topic] = msg.payload

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="recheck-trim", protocol=mqtt.MQTTv311)
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_m
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    topics = [
        "homeassistant/camera/hakiosk_tablet/front/config",
        "homeassistant/sensor/hakiosk_tablet/camera_status/config",
        "homeassistant/sensor/hakiosk_tablet/camera_stream_url/config",
        "homeassistant/button/hakiosk_tablet/camera_snapshot/config",
        "homeassistant/camera/hakiosk_tablet/front_stream/config",
        "homeassistant/switch/hakiosk_tablet/camera/config",
    ]
    for t in topics:
        cli.subscribe(t)
    cli.loop_start()
    time.sleep(3)
    cli.loop_stop()
    cli.disconnect()
    c.close()
    for t in topics:
        p = seen.get(t)
        name = t.split("/")[-2]
        print(f"{name}: {'GONE' if not p else f'PRESENT ({len(p)}B)'}")


if __name__ == "__main__":
    main()
