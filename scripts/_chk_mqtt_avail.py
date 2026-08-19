#!/usr/bin/env python3
import paramiko
import paho.mqtt.client as mqtt
import time

HOST = "192.168.8.201"
PASS = "kiosk"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
# install unit
sftp = c.open_sftp()
data = open(r"C:\Users\ben_s\Projects\linx-ha-kiosk\scripts\ha-kiosk-mqtt.service", "rb").read().replace(b"\r\n", b"\n")
with sftp.file("/tmp/ha-kiosk-mqtt.service", "wb") as f:
    f.write(data)
sftp.close()
_, o, _ = c.exec_command(
    f"echo {PASS} | sudo -S -p '' bash -c 'install -m 644 /tmp/ha-kiosk-mqtt.service /etc/systemd/system/ha-kiosk-mqtt.service; systemctl daemon-reload; cat /opt/ha-kiosk/mqtt.env'",
    timeout=30,
    get_pty=True,
)
env_txt = o.read().decode()
env = {}
for line in env_txt.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip().strip('"').strip("'")
c.close()

seen = {"status": None}

def on_message(_c, _u, msg):
    if msg.topic.endswith("/status"):
        seen["status"] = msg.payload.decode()
        print("got", seen["status"])

cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="chk-avail2", protocol=mqtt.MQTTv311)
user = env.get("MQTT_USER") or env.get("MQTT_USERNAME")
if user:
    cli.username_pw_set(user, env.get("MQTT_PASSWORD") or env.get("MQTT_PASS") or "")
cli.on_message = on_message
cli.connect(env.get("MQTT_HOST", "192.168.8.110"), int(env.get("MQTT_PORT", "1883")), 60)
cli.subscribe("hakiosk/hakiosk_tablet/status")
cli.loop_start()
for i in range(15):
    if seen["status"]:
        break
    time.sleep(0.5)
cli.loop_stop()
cli.disconnect()
print("availability=", seen["status"])
raise SystemExit(0 if seen["status"] == "online" else 1)
