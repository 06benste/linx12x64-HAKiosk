#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    body = pathlib.Path(__file__).with_name("_cam_stream_probe.sh").read_text(encoding="utf-8")
    body = body.replace("\r\n", "\n")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-stream-probe.sh", "w") as f:
        f.write(body)
    sftp.chmod("/tmp/cam-stream-probe.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/cam-stream-probe.sh",
        timeout=120,
        get_pty=True,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    print("exit", stdout.channel.recv_exit_status())
    c.close()


if __name__ == "__main__":
    main()
