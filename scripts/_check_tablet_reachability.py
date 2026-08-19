#!/usr/bin/env python3
import socket
import urllib.request

import paramiko

HOST = "192.168.8.201"


def tcp(port: int) -> str:
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((HOST, port))
        s.close()
        return "open"
    except Exception as e:
        return f"closed ({e})"


def http(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            body = r.read()[:160]
            return f"OK {r.status} {body!r}"
    except Exception as e:
        return f"FAIL {type(e).__name__}: {e}"


def main() -> None:
    print(f"host {HOST}")
    for port in (22, 17823, 17824):
        print(f"tcp {port}: {tcp(port)}")
    print("power:", http(f"http://{HOST}:17823/health"))
    print("stream:", http(f"http://{HOST}:17824/health"))
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(
            HOST,
            username="kioskuser",
            password="kiosk",
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
        )
        _, o, _ = c.exec_command(
            "uptime; hostname; systemctl is-active ha-kiosk-mqtt.service ha-kiosk-camera-stream.service 2>/dev/null || true",
            timeout=12,
        )
        print("ssh: OK")
        print(o.read().decode().strip())
        c.close()
    except Exception as e:
        print(f"ssh: FAIL {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
