#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -x
# Hard-kill wedged camera users
systemctl kill -s SIGKILL ha-kiosk-mqtt.service || true
systemctl stop ha-kiosk-mqtt.service || true
pkill -9 -f '/opt/ha-kiosk/scripts/ha-kiosk-mqtt.py' || true
pkill -9 -f 'v4l2-ctl' || true
pkill -9 -f 'ffmpeg' || true
sleep 1

install -m 755 /tmp/ha-fix/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
install -m 755 /tmp/ha-fix/capture-tablet-cam.py /opt/ha-kiosk/scripts/capture-tablet-cam.py
install -m 644 /tmp/ha-fix/camera_preview.py /opt/ha-kiosk/scripts/camera_preview.py
install -m 755 /tmp/ha-fix/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py

systemctl restart ha-kiosk-camera-stream.service
sleep 5
curl -m 5 -sS http://127.0.0.1:17824/health || true
echo
curl -m 25 -sS -o /tmp/t.jpg -w 'snap=%{http_code} size=%{size_download}\n' http://127.0.0.1:17824/snapshot.jpg || true
ls -la /tmp/t.jpg || true

systemctl reset-failed ha-kiosk-mqtt.service || true
systemctl start ha-kiosk-mqtt.service
sleep 6
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service || true
journalctl -u ha-kiosk-mqtt.service -n 20 --no-pager || true
journalctl -u ha-kiosk-camera-stream.service -n 15 --no-pager || true
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-fix")
    except OSError:
        pass
    for name in ("ha-kiosk-mqtt.py", "capture-tablet-cam.py", "camera_preview.py", "camera-stream-server.py"):
        with sftp.file(f"/tmp/ha-fix/{name}", "wb") as f:
            f.write((ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
        print("up", name, flush=True)
    with sftp.file("/tmp/ha-fix.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/ha-fix.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/ha-fix.sh",
        timeout=120,
        get_pty=True,
    )
    # Don't hang forever on readline
    stdout.channel.settimeout(90)
    try:
        print(stdout.read().decode(errors="replace"), flush=True)
    except Exception as exc:
        print("read:", exc, flush=True)
    print("exit", stdout.channel.recv_exit_status(), flush=True)

    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' cat /opt/ha-kiosk/mqtt.env", timeout=20, get_pty=True)
    env = {}
    for line in o.read().decode().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

    import paho.mqtt.client as mqtt

    seen = {"disc": False, "bytes": 0, "url": ""}

    def on_message(_c, _u, msg):
        if "front_stream/config" in msg.topic:
            seen["disc"] = True
            print("DISC", msg.payload[:180], flush=True)
        elif msg.topic.endswith("/camera_stream"):
            seen["bytes"] = max(seen["bytes"], len(msg.payload))
        elif msg.topic.endswith("/camera_stream_url"):
            seen["url"] = msg.payload.decode()

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="v-stream2", protocol=mqtt.MQTTv311)
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    cli.subscribe("homeassistant/camera/hakiosk_tablet/front_stream/config")
    cli.subscribe("hakiosk/hakiosk_tablet/camera_stream")
    cli.subscribe("hakiosk/hakiosk_tablet/camera_stream_url")
    cli.loop_start()
    for i in range(25):
        print(i, seen, flush=True)
        if seen["disc"] and seen["bytes"] > 800:
            break
        time.sleep(1)
    cli.loop_stop()
    cli.disconnect()
    c.close()
    print("FINAL", seen, flush=True)
    if not seen["disc"]:
        raise SystemExit(1)
    print("OK", flush=True)


if __name__ == "__main__":
    main()
