#!/usr/bin/env python3
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""
set -euxo pipefail
pkill -9 -f 'v4l2-ctl' || true
systemctl reset-failed ha-kiosk-camera-stream.service ha-kiosk-mqtt.service || true
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service
sleep 5
systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service
curl -fsS --max-time 5 http://127.0.0.1:17824/health || true
echo
journalctl -u ha-kiosk-mqtt.service -n 12 --no-pager
"""


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/up-mqtt.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/up-mqtt.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/up-mqtt.sh", timeout=60, get_pty=True)
    print(o.read().decode())
    c.close()
    time.sleep(2)
    try:
        print("stream", urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=5).read().decode())
    except Exception as e:
        print("stream", e)


if __name__ == "__main__":
    main()
