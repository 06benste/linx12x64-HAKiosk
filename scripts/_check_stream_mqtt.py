#!/usr/bin/env python3
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def main() -> None:
    for i in range(12):
        try:
            d = urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=3).read()
            print("health", d.decode())
            break
        except Exception as e:
            print("wait", i, e)
            time.sleep(2)
    else:
        print("stream never came up")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' journalctl -u ha-kiosk-mqtt.service -n 20 --no-pager",
        timeout=20,
        get_pty=True,
    )
    print(o.read().decode()[-1500:])
    c.close()


if __name__ == "__main__":
    main()
