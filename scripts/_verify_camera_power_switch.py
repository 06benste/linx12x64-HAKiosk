#!/usr/bin/env python3
"""Verify HA Camera switch stops/starts ha-kiosk-camera-stream.service."""
from __future__ import annotations

import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def ssh(c: paramiko.SSHClient, cmd: str, timeout: float = 60) -> str:
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash -lc {cmd!r}",
        timeout=timeout,
        get_pty=True,
    )
    out = o.read().decode("utf-8", "replace")
    o.channel.recv_exit_status()
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)

    env_txt = ssh(c, "cat /opt/ha-kiosk/mqtt.env")
    env: dict[str, str] = {}
    for line in env_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

    host = env.get("MQTT_HOST", "192.168.8.110")
    port = int(env.get("MQTT_PORT", "1883"))
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    password = env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or ""

    import paho.mqtt.client as mqtt

    state: dict[str, str] = {"power": "", "status": ""}

    def on_message(_cli, _u, msg):
        if msg.topic.endswith("/camera_power"):
            state["power"] = msg.payload.decode("utf-8", "replace")
        elif msg.topic.endswith("/camera_status"):
            state["status"] = msg.payload.decode("utf-8", "replace")

    cli = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="verify-hakiosk-cam-power",
        protocol=mqtt.MQTTv311,
    )
    if user:
        cli.username_pw_set(user, password)
    cli.on_message = on_message
    cli.connect(host, port, 60)
    cli.subscribe("hakiosk/hakiosk_tablet/camera_power")
    cli.subscribe("hakiosk/hakiosk_tablet/camera_status")
    cli.subscribe("homeassistant/switch/hakiosk_tablet/camera/config")
    cli.loop_start()

    print("=== switch OFF ===", flush=True)
    cli.publish("hakiosk/hakiosk_tablet/cmd/camera", "OFF", qos=1)
    for _ in range(20):
        time.sleep(0.5)
        if state["power"] == "OFF":
            break
    active = ssh(c, "systemctl is-active ha-kiosk-camera-stream.service || true").strip().splitlines()[-1]
    print(f"power={state['power']!r} status={state['status']!r} stream={active!r}", flush=True)
    if state["power"] != "OFF" or active != "inactive":
        raise SystemExit("OFF failed")

    print("=== switch ON ===", flush=True)
    cli.publish("hakiosk/hakiosk_tablet/cmd/camera", "ON", qos=1)
    for _ in range(30):
        time.sleep(0.5)
        active = ssh(c, "systemctl is-active ha-kiosk-camera-stream.service || true").strip().splitlines()[-1]
        if state["power"] == "ON" and active == "active":
            break
    print(f"power={state['power']!r} status={state['status']!r} stream={active!r}", flush=True)
    if state["power"] != "ON" or active != "active":
        raise SystemExit("ON failed")

    journal = ssh(c, "journalctl -u ha-kiosk-mqtt.service -n 25 --no-pager")
    print(journal[-2500:], flush=True)

    cli.loop_stop()
    cli.disconnect()
    c.close()
    print("OK", flush=True)


if __name__ == "__main__":
    main()
