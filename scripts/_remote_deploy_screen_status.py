#!/usr/bin/env python3
"""Deploy power-api + mqtt bridge for screen status entity."""
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
install -m 755 /tmp/ha-screen/power-api.py /opt/ha-kiosk/scripts/power-api.py
install -m 755 /tmp/ha-screen/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
systemctl restart ha-kiosk-power.service
systemctl restart ha-kiosk-mqtt.service
sleep 2
systemctl is-active ha-kiosk-power.service ha-kiosk-mqtt.service
curl -fsS http://127.0.0.1:17823/status | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("display"))'
journalctl -u ha-kiosk-mqtt.service -n 12 --no-pager
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-screen")
    except OSError:
        pass
    for name in ("power-api.py", "ha-kiosk-mqtt.py"):
        data = (ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(f"/tmp/ha-screen/{name}", "wb") as f:
            f.write(data)
        print("uploaded", name, flush=True)
    with sftp.file("/tmp/deploy-screen-status.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/deploy-screen-status.sh", 0o755)
    sftp.close()

    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/deploy-screen-status.sh",
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

    # Verify MQTT discovery + state
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' cat /opt/ha-kiosk/mqtt.env", timeout=20, get_pty=True)
    env: dict[str, str] = {}
    for line in o.read().decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

    import paho.mqtt.client as mqtt

    seen = {"cfg": False, "state": ""}

    def on_message(_cli, _u, msg):
        if msg.topic.endswith("/screen_status/config") and msg.payload:
            seen["cfg"] = True
        elif msg.topic.endswith("/screen_status") and not msg.topic.endswith("/config"):
            seen["state"] = msg.payload.decode("utf-8", "replace")

    cli = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="verify-screen-status",
        protocol=mqtt.MQTTv311,
    )
    user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
    if user:
        cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
    cli.on_message = on_message
    cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
    cli.subscribe("homeassistant/sensor/hakiosk_tablet/screen_status/config")
    cli.subscribe("hakiosk/hakiosk_tablet/screen_status")
    cli.loop_start()
    for _ in range(20):
        if seen["cfg"] and seen["state"]:
            break
        time.sleep(0.5)
    cli.loop_stop()
    cli.disconnect()
    c.close()
    print(f"discovery={seen['cfg']} state={seen['state']!r}", flush=True)
    if not seen["cfg"] or seen["state"] not in ("on", "blanked", "unknown"):
        raise SystemExit("screen status entity not ready")
    print("OK", flush=True)


if __name__ == "__main__":
    main()
