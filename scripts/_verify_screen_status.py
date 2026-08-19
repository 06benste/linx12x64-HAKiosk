#!/usr/bin/env python3
"""Toggle blank/wake and confirm screen_status MQTT state."""
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

    state = {"v": ""}

    def on_message(_cli, _u, msg):
        if msg.topic.endswith("/screen_status"):
            state["v"] = msg.payload.decode("utf-8", "replace")

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-screen", protocol=mqtt.MQTTv311)
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    cli.subscribe("hakiosk/hakiosk_tablet/screen_status")
    cli.loop_start()

    print("blank…", flush=True)
    cli.publish("hakiosk/hakiosk_tablet/cmd/display_blank", "PRESS", qos=1)
    for _ in range(20):
        time.sleep(0.3)
        if state["v"] == "blanked":
            break
    print("state=", state["v"], flush=True)
    if state["v"] != "blanked":
        raise SystemExit("expected blanked")

    print("wake…", flush=True)
    cli.publish("hakiosk/hakiosk_tablet/cmd/display_wake", "PRESS", qos=1)
    for _ in range(20):
        time.sleep(0.3)
        if state["v"] == "on":
            break
    print("state=", state["v"], flush=True)
    if state["v"] != "on":
        raise SystemExit("expected on")

    cli.loop_stop()
    cli.disconnect()
    c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
