#!/usr/bin/env python3
"""Check whether the HA Camera switch left the tablet camera fully on."""
from __future__ import annotations

import sys
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def ssh(c: paramiko.SSHClient, cmd: str, timeout: float = 30) -> str:
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

    stream = ssh(c, "systemctl is-active ha-kiosk-camera-stream.service || true").strip().splitlines()[-1]
    mqtt = ssh(c, "systemctl is-active ha-kiosk-mqtt.service || true").strip().splitlines()[-1]
    power_file = ssh(c, "cat /opt/ha-kiosk/config/camera_power 2>/dev/null || echo MISSING").strip().splitlines()[-1]
    procs = ssh(
        c,
        "ps -eo pid,cmd | awk '/camera-stream-server\\.py|[v]4l2-ctl --stream/ {print}' || true",
    ).strip()
    listen = ssh(c, "ss -ltn 'sport = :17824' || true").strip()
    journal = ssh(c, "journalctl -u ha-kiosk-mqtt.service -n 25 --no-pager")

    env_txt = ssh(c, "cat /opt/ha-kiosk/mqtt.env")
    env: dict[str, str] = {}
    for line in env_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

    import paho.mqtt.client as mqtt_mod

    seen = {"power": "", "status": ""}

    def on_message(_cli, _u, msg):
        if msg.topic.endswith("/camera_power"):
            seen["power"] = msg.payload.decode("utf-8", "replace")
        elif msg.topic.endswith("/camera_status"):
            seen["status"] = msg.payload.decode("utf-8", "replace")

    cli = mqtt_mod.Client(
        mqtt_mod.CallbackAPIVersion.VERSION2,
        client_id="check-cam-on",
        protocol=mqtt_mod.MQTTv311,
    )
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    cli.subscribe("hakiosk/hakiosk_tablet/camera_power")
    cli.subscribe("hakiosk/hakiosk_tablet/camera_status")
    cli.loop_start()
    for _ in range(20):
        if seen["power"]:
            break
        time.sleep(0.25)
    cli.loop_stop()
    cli.disconnect()

    http_ok = False
    http_body = ""
    try:
        with urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=5) as resp:
            http_body = resp.read()[:120].decode("utf-8", "replace")
            http_ok = resp.status == 200
    except Exception as exc:  # noqa: BLE001
        http_body = f"{type(exc).__name__}: {exc}"

    snap_ok = False
    snap_err = ""
    try:
        with urllib.request.urlopen(f"http://{HOST}:17824/snapshot.jpg", timeout=15) as resp:
            data = resp.read()
            snap_ok = len(data) > 800 and data[:2] == b"\xff\xd8"
            snap_err = f"{len(data)} bytes"
    except Exception as exc:  # noqa: BLE001
        snap_err = f"{type(exc).__name__}: {exc}"

    print(f"stream_service={stream}")
    print(f"mqtt_service={mqtt}")
    print(f"power_file={power_file!r}")
    print(f"mqtt_power={seen['power']!r} mqtt_status={seen['status']!r}")
    print(f"http_health={'up' if http_ok else 'down'} ({http_body})")
    print(f"snapshot={'ok' if snap_ok else 'fail'} ({snap_err})")
    print("--- processes ---")
    print(procs if procs else "(none)")
    print("--- listen :17824 ---")
    print(listen if listen else "(empty)")
    print("--- journal (tail) ---")
    print(journal[-1600:])

    ok = (
        stream == "active"
        and mqtt == "active"
        and power_file.strip() in ("1", "on", "true", "yes")
        and seen["power"] == "ON"
        and http_ok
        and snap_ok
        and "camera-stream-server" in procs
    )
    c.close()
    if not ok:
        raise SystemExit("NOT fully on")
    print("VERIFIED: camera is on")


if __name__ == "__main__":
    main()
