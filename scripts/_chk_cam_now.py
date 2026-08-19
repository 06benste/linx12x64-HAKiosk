#!/usr/bin/env python3
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""
set -x
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service
ss -lntp | grep 17824 || true
journalctl -u ha-kiosk-camera-stream.service -n 25 --no-pager
journalctl -u ha-kiosk-mqtt.service -n 15 --no-pager
curl -sS --max-time 5 http://127.0.0.1:17824/health || true
echo
curl -sS --max-time 20 -o /tmp/t.jpg -w 'snap=%{http_code} size=%{size_download}\n' http://127.0.0.1:17824/snapshot.jpg || true
"""


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/chk.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/chk.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/chk.sh", timeout=60, get_pty=True)
    print(o.read().decode())
    c.close()


if __name__ == "__main__":
    main()
