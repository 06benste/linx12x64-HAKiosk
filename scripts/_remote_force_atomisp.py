#!/usr/bin/env python3
"""Upload and run _force_atomisp.sh on the Linx tablet."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = pathlib.Path(__file__).with_name("_force_atomisp.sh")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    body = SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        username="kioskuser",
        password=PASS,
        timeout=25,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    with sftp.file("/tmp/force-atomisp.sh", "w") as f:
        f.write(body)
    sftp.chmod("/tmp/force-atomisp.sh", 0o755)
    sftp.close()
    print("starting atomisp install/build on tablet (may take 20-60+ min)...", flush=True)
    _, stdout, stderr = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/force-atomisp.sh",
        timeout=7200,
        get_pty=True,
    )
    # Stream output live
    while True:
        line = stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
        sys.stdout.flush()
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print(
            "STDERR:",
            "\n".join(l for l in err.splitlines() if "password" not in l.lower()),
            flush=True,
        )
    code = stdout.channel.recv_exit_status()
    print("exit", code, flush=True)
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
