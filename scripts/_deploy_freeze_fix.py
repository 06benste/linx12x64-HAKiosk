#!/usr/bin/env python3
import json
import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    return c


def sudo_script(c, body: str, timeout: int = 90) -> str:
    sftp = c.open_sftp()
    with sftp.file("/tmp/_agent_job.sh", "w") as f:
        f.write("#!/bin/bash\nset -e\n" + body + "\n")
    sftp.chmod("/tmp/_agent_job.sh", 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(timeout)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_agent_job.sh")
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    else:
        chan.close()
        raise TimeoutError(buf.decode(errors="replace")[-500:])
    return buf.decode(errors="replace")


def health(c):
    out = sudo_script(c, "curl -fsS --max-time 3 http://127.0.0.1:17824/health", timeout=20)
    line = [ln for ln in out.splitlines() if ln.strip().startswith("{")][-1]
    return json.loads(line)


def main():
    c = connect()
    sftp = c.open_sftp()
    for name in ("camera-stream-server.py", "ha-kiosk-mqtt.py"):
        with sftp.file(f"/tmp/{name}", "wb") as f:
            f.write((ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n"))
    sftp.close()
    print(
        sudo_script(
            c,
            "install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py; "
            "install -m 755 /tmp/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py; "
            "systemctl restart ha-kiosk-camera-stream.service; "
            "systemctl restart ha-kiosk-mqtt.service; "
            "sleep 8; curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo",
            timeout=50,
        )
    )
    prev = None
    for i in range(10):
        h = health(c)
        delta = None if prev is None else h["frames"] - prev
        print(
            f"i={i} frames={h['frames']}(+{delta}) age={h.get('last_frame_age_s')} "
            f"clients={h['clients']} streaming={h['streaming']} restarts={h['restarts']}"
        )
        prev = h["frames"]
        time.sleep(3)
    print(
        sudo_script(
            c,
            "journalctl -u ha-kiosk-camera-stream.service -n 25 --no-pager -o short-iso | "
            "grep -E 'watchdog|started|stopped|error|FW' || true",
            timeout=25,
        )
    )
    c.close()


if __name__ == "__main__":
    main()
