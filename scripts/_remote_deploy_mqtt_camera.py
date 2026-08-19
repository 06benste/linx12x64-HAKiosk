#!/usr/bin/env python3
"""Deploy MQTT camera bridge (switch + live stream) to the tablet."""
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
install -d -m 755 /opt/ha-kiosk/scripts
install -m 755 /tmp/ha-cam/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
systemctl restart ha-kiosk-mqtt.service
sleep 3
systemctl is-active ha-kiosk-mqtt.service
journalctl -u ha-kiosk-mqtt.service -n 25 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-cam")
    except OSError:
        pass
    data = (ROOT / "scripts" / "ha-kiosk-mqtt.py").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/ha-cam/ha-kiosk-mqtt.py", "wb") as f:
        f.write(data)
    print("uploaded ha-kiosk-mqtt.py", flush=True)
    with sftp.file("/tmp/deploy-mqtt-cam.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-mqtt-cam.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-mqtt-cam.sh",
        timeout=120,
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
    env_txt = o.read().decode("utf-8", "replace")
    env: dict[str, str] = {}
    for line in env_txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

    import paho.mqtt.client as mqtt

    seen: dict[str, object] = {
        "front_cfg": None,
        "status_cfg": None,
        "url_cfg": None,
        "snap_cfg": None,
        "stream_cfg": False,
        "switch_cfg": False,
        "stream_bytes": 0,
    }

    def on_message(_c, _u, msg):
        payload = msg.payload
        if msg.topic.endswith("/front/config"):
            seen["front_cfg"] = payload
        elif msg.topic.endswith("/camera_status/config"):
            seen["status_cfg"] = payload
        elif msg.topic.endswith("/camera_stream_url/config"):
            seen["url_cfg"] = payload
        elif msg.topic.endswith("/camera_snapshot/config"):
            seen["snap_cfg"] = payload
        elif msg.topic.endswith("/front_stream/config") and payload:
            seen["stream_cfg"] = True
        elif "/switch/hakiosk_tablet/camera/config" in msg.topic and payload:
            seen["switch_cfg"] = True
        elif msg.topic.endswith("/camera_stream"):
            seen["stream_bytes"] = len(payload)

    cli = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="verify-hakiosk-cam-trim",
        protocol=mqtt.MQTTv311,
    )
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    for t in (
        "homeassistant/camera/hakiosk_tablet/front/config",
        "homeassistant/sensor/hakiosk_tablet/camera_status/config",
        "homeassistant/sensor/hakiosk_tablet/camera_stream_url/config",
        "homeassistant/button/hakiosk_tablet/camera_snapshot/config",
        "homeassistant/camera/hakiosk_tablet/front_stream/config",
        "homeassistant/switch/hakiosk_tablet/camera/config",
        "hakiosk/hakiosk_tablet/camera_stream",
    ):
        cli.subscribe(t)
    cli.loop_start()
    for i in range(25):
        time.sleep(1)
        if seen["stream_bytes"] and i > 3:
            break
        if i in (5, 12, 20):
            print(f"… waiting stream frames ({i}s) bytes={seen['stream_bytes']}", flush=True)
    cli.loop_stop()
    cli.disconnect()
    c.close()

    def gone(v: object) -> bool:
        # Empty retained publish deletes the broker message; later subscribers see nothing.
        return v is None or v == b"" or v == ""

    print(
        "removed_front=", gone(seen["front_cfg"]),
        "removed_status=", gone(seen["status_cfg"]),
        "removed_url=", gone(seen["url_cfg"]),
        "removed_snapshot=", gone(seen["snap_cfg"]),
        "stream_cfg=", seen["stream_cfg"],
        "switch_cfg=", seen["switch_cfg"],
        "stream_bytes=", seen["stream_bytes"],
        flush=True,
    )
    if not (
        gone(seen["front_cfg"])
        and gone(seen["status_cfg"])
        and gone(seen["url_cfg"])
        and gone(seen["snap_cfg"])
        and seen["stream_cfg"]
        and seen["switch_cfg"]
    ):
        raise SystemExit("discovery trim incomplete")
    print("OK", flush=True)


if __name__ == "__main__":
    main()
