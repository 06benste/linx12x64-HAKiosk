#!/usr/bin/env python3
import pathlib
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
REMOTE = r"""
set -x
/opt/ha-kiosk/scripts/load-atomisp.sh >/tmp/load.log 2>&1 || true
v4l2-ctl -d /dev/video0 --get-fmt-video || true
rm -f /tmp/two.nv12 /tmp/probe_cap.jpg
timeout -s KILL 30 v4l2-ctl -d /dev/video0 --stream-mmap=4 --stream-count=2 --stream-to=/tmp/two.nv12 || true
ls -la /tmp/two.nv12 || true
python3 - <<'PY'
import os
p='/tmp/two.nv12'
n=os.path.getsize(p) if os.path.exists(p) else 0
print('raw', n)
if n:
    print('per', n/2, 'mod2842624', n%2842624, 'mod2841600', n%(1600*1184*3//2))
PY
/opt/ha-kiosk/scripts/capture-tablet-cam.py /tmp/probe_cap.jpg || true
ls -la /tmp/probe_cap.jpg || true
tail -20 /tmp/load.log || true
"""


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/test-cam.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/test-cam.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/test-cam.sh", timeout=120, get_pty=True)
    print(o.read().decode())
    sftp = c.open_sftp()
    try:
        sftp.get("/tmp/probe_cap.jpg", str(ROOT / "logs" / "probe_cap.jpg"))
        print("saved probe_cap.jpg")
    except Exception as e:
        print("no probe", e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
