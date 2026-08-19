#!/usr/bin/env python3
import pathlib
import sys
import time

import paramiko

HOST = "192.168.8.201"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="kioskuser", password="kiosk", timeout=15, allow_agent=False, look_for_keys=False)

    sftp = client.open_sftp()
    data = (ROOT / "scripts" / "_remote_fix_fullscreen.sh").read_bytes().replace(b"\r\n", b"\n")
    with sftp.file("/tmp/fix-fullscreen.sh", "wb") as f:
        f.write(data)
    sftp.chmod("/tmp/fix-fullscreen.sh", 0o755)
    sftp.close()

    stdin, stdout, stderr = client.exec_command(
        "echo kiosk | sudo -S -p '' bash /tmp/fix-fullscreen.sh", timeout=180
    )
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    print(out[-5000:])
    lines = [l for l in err.splitlines() if "password" not in l.lower()]
    if lines:
        print("STDERR:\n" + "\n".join(lines)[-3000:])
    print("exit:", code)
    if code != 0 or "FIX_OK" not in out:
        client.close()
        sys.exit(1)

    print("waiting for X restart...")
    time.sleep(15)
    stdin, stdout, stderr = client.exec_command(
        "DISPLAY=:0 xwininfo -root -tree 2>/dev/null | head -n 25; echo ---; "
        "DISPLAY=:0 xrandr --current | head -n 3",
        timeout=20,
    )
    print(stdout.read().decode("utf-8", errors="replace"))
    client.close()


if __name__ == "__main__":
    main()
