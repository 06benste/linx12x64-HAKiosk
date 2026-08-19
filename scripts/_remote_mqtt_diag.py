#!/usr/bin/env python3
"""Diagnose MQTT auth in detail and restart bridge."""
from __future__ import annotations

import sys
import time

import paramiko

try:
    import paho.mqtt.client as mqtt
except ImportError:
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "paho-mqtt", "-q"])
    import paho.mqtt.client as mqtt

HOST_HA = "192.168.8.110"
USER = "kioskuser"
PW = "kiosk"


def try_mqtt(label: str, user: str | None, pw: str | None) -> None:
    result = {"rc": None, "err": None}

    def on_connect(c, u, f, rc, props=None):
        result["rc"] = rc
        result["rc_repr"] = repr(rc)
        try:
            result["rc_int"] = int(getattr(rc, "value", rc))
        except Exception:
            result["rc_int"] = None
        c.disconnect()

    def on_connect_fail(c, u, f):
        result["err"] = "connect_fail"

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"diag-{label}", protocol=mqtt.MQTTv311)
    if user is not None:
        c.username_pw_set(user, pw or "")
    c.on_connect = on_connect
    try:
        c.connect(HOST_HA, 1883, 10)
        c.loop_start()
        time.sleep(3)
        c.loop_stop()
    except Exception as exc:
        result["err"] = str(exc)
    print(label, result)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=== from PC ===")
    try_mqtt("anon", None, None)
    try_mqtt("kioskuser", USER, PW)
    try_mqtt("kioskuser-empty", USER, "")

    # Push env again + restart on tablet and capture fresh logs
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.8.201", username="kioskuser", password="kiosk", timeout=15, allow_agent=False, look_for_keys=False)
    script = r"""
cat > /opt/ha-kiosk/mqtt.env <<'EOF'
MQTT_HOST=192.168.8.110
MQTT_PORT=1883
MQTT_USER=kioskuser
MQTT_PASSWORD=kiosk
MQTT_INTERVAL=15
EOF
chmod 600 /opt/ha-kiosk/mqtt.env
systemctl restart ha-kiosk-mqtt.service
sleep 4
# local mqtt test with python
python3 - <<'PY'
import time
import paho.mqtt.client as mqtt
res={'rc':None}
def on_connect(c,u,f,rc,props=None):
    res['rc']=repr(rc)
    print('tablet-broker connect', rc)
    if int(getattr(rc,'value',rc))==0:
        c.publish('hakiosk/test', 'ping', qos=0)
    c.disconnect()
c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='tablet-diag')
c.username_pw_set('kioskuser','kiosk')
c.on_connect=on_connect
c.connect('192.168.8.110',1883,10)
c.loop_start(); time.sleep(3); c.loop_stop()
print('res', res)
PY
journalctl -u ha-kiosk-mqtt.service -n 15 --no-pager
"""
    sftp = client.open_sftp()
    with sftp.file("/tmp/mqtt-diag.sh", "w") as f:
        f.write(script.replace("\r\n", "\n"))
    sftp.chmod("/tmp/mqtt-diag.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = client.exec_command("echo kiosk | sudo -S -p '' bash /tmp/mqtt-diag.sh", timeout=60)
    print("=== from tablet ===")
    print(stdout.read().decode())
    err = stderr.read().decode()
    print("STDERR:", "\n".join(l for l in err.splitlines() if "password" not in l.lower())[-1500:])
    client.close()


if __name__ == "__main__":
    main()
