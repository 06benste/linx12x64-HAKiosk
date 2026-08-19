#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    data = (ROOT / "scripts" / "_remote_snap_stats.py").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/snap_stats.py", "wb") as f:
        f.write(data)
    sftp.chmod("/tmp/snap_stats.py", 0o755)
    sftp.close()
    _, o, e = c.exec_command("python3 /tmp/snap_stats.py", timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err)
    sftp = c.open_sftp()
    for name in ("graded.jpg", "plain.jpg"):
        blob = sftp.file(f"/tmp/{name}", "rb").read()
        (OUT / name).write_bytes(blob)
        print("saved", name, len(blob), flush=True)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
