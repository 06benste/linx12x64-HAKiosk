#!/usr/bin/env python3
import pathlib
import time
import urllib.request

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    for i in range(3):
        data = urllib.request.urlopen(f"http://{HOST}:17824/snapshot.jpg", timeout=30).read()
        p = ROOT / "logs" / f"stream_snap_{i}.jpg"
        p.write_bytes(data)
        print(i, len(data), p, flush=True)
        time.sleep(0.5)
    print("health", urllib.request.urlopen(f"http://{HOST}:17824/health", timeout=5).read().decode(), flush=True)

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' journalctl -u ha-kiosk-camera-stream.service -n 20 --no-pager",
        timeout=20,
        get_pty=True,
    )
    print(o.read().decode()[-1500:], flush=True)
    _, o, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' /opt/ha-kiosk/scripts/capture-tablet-cam.py /tmp/clean_still.jpg",
        timeout=60,
        get_pty=True,
    )
    print(o.read().decode()[-400:], flush=True)
    sftp = c.open_sftp()
    try:
        sftp.get("/tmp/clean_still.jpg", str(ROOT / "logs" / "clean_still.jpg"))
        print("got clean_still", flush=True)
    except Exception as e:
        print("no clean", e, flush=True)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
