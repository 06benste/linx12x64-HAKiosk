#!/usr/bin/env python3
"""Deploy fixed MQTT bridge + ensure stream/mqtt are online."""
from __future__ import annotations

import pathlib
import sys
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 755 /tmp/ha-fix/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
install -m 644 /tmp/ha-fix/ha-kiosk-mqtt.service /etc/systemd/system/ha-kiosk-mqtt.service
install -m 644 /tmp/ha-fix/ha-kiosk-camera-stream.service /etc/systemd/system/ha-kiosk-camera-stream.service
systemctl daemon-reload
systemctl enable ha-kiosk-mqtt.service ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-camera-stream.service
sleep 3
systemctl restart ha-kiosk-mqtt.service
sleep 4
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
echo
journalctl -u ha-kiosk-mqtt.service -n 20 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Harden mqtt unit stop behaviour (orphaned v4l2-ctl was wedging stops)
    unit = (ROOT / "scripts" / "ha-kiosk-mqtt.service").read_text(encoding="utf-8")
    if "KillMode=" not in unit:
        unit = unit.replace(
            "RestartSec=5\n",
            "RestartSec=5\nKillMode=control-group\nTimeoutStopSec=10\n"
            "ExecStopPost=-/bin/bash -c '/usr/bin/pkill -9 -f \"v4l2-ctl --stream\" || true'\n",
        )
        (ROOT / "scripts" / "ha-kiosk-mqtt.service").write_text(unit, encoding="utf-8")

    stream_unit = (ROOT / "scripts" / "ha-kiosk-camera-stream.service").read_text(encoding="utf-8")
    if "ha-kiosk-mqtt.service" not in stream_unit and "Before=" not in stream_unit:
        # Start stream before mqtt so availability + camera frames work at boot
        stream_unit = stream_unit.replace(
            "After=network-online.target ha-kiosk-atomisp.service\nWants=network-online.target\n",
            "After=network-online.target ha-kiosk-atomisp.service\n"
            "Wants=network-online.target\n"
            "Before=ha-kiosk-mqtt.service\n",
        )
        (ROOT / "scripts" / "ha-kiosk-camera-stream.service").write_text(stream_unit, encoding="utf-8")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-fix")
    except OSError:
        pass
    for name in ("ha-kiosk-mqtt.py", "ha-kiosk-mqtt.service", "ha-kiosk-camera-stream.service"):
        with sftp.file(f"/tmp/ha-fix/{name}", "wb") as f:
            f.write((ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
        print("up", name, flush=True)
    with sftp.file("/tmp/ha-fix.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/ha-fix.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/ha-fix.sh",
        timeout=90,
        get_pty=True,
    )
    print(stdout.read().decode(errors="replace"), flush=True)
    c.close()

    time.sleep(2)
    try:
        print("stream", urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=5).read().decode())
    except Exception as e:
        print("stream", e)

    # Confirm availability retained online on broker
    _, o, _ = paramiko.SSHClient(), None
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' cat /opt/ha-kiosk/mqtt.env", timeout=20, get_pty=True)
    env = {}
    for line in o.read().decode().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    import paho.mqtt.client as mqtt

    seen = {"status": None}

    def on_message(_c, _u, msg):
        if msg.topic.endswith("/status"):
            seen["status"] = msg.payload.decode()

    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="chk-avail", protocol=mqtt.MQTTv311)
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    cli.subscribe("hakiosk/hakiosk_tablet/status")
    cli.loop_start()
    for _ in range(10):
        if seen["status"]:
            break
        time.sleep(0.5)
    cli.loop_stop()
    cli.disconnect()
    c.close()
    print("mqtt availability:", seen["status"], flush=True)
    if seen["status"] != "online":
        raise SystemExit(1)
    print("OK", flush=True)


if __name__ == "__main__":
    main()
