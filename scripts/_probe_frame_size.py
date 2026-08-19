#!/usr/bin/env python3
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
REMOTE = r"""
set -x
pkill -9 -f 'v4l2-ctl' || true
pkill -9 -f 'ffmpeg' || true
sleep 1
/opt/ha-kiosk/scripts/load-atomisp.sh || true
sleep 2
v4l2-ctl -d /dev/video0 --get-fmt-video
rm -f /tmp/three.nv12
timeout -s KILL 25 v4l2-ctl -d /dev/video0 --stream-mmap=4 --stream-count=3 --stream-to=/tmp/three.nv12
ls -la /tmp/three.nv12
python3 - <<'PY'
import os
n=os.path.getsize("/tmp/three.nv12")
print("bytes", n)
print("per_frame_if_3", n/3 if n else 0)
print("theory_nv12", 1600*1184*3//2)
print("size_image", 2842624)
if n:
    print("mod_size_image", n % 2842624)
    print("mod_theory", n % (1600*1184*3//2))
PY
/opt/ha-kiosk/scripts/capture-tablet-cam.py /tmp/probe_cap.jpg
ls -la /tmp/probe_cap.jpg
"""


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/probe-frame.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/probe-frame.sh", 0o755)
    sftp.close()
    _, stdout, _ = c.exec_command(
        f"echo {PASS} | sudo -S -p '' bash /tmp/probe-frame.sh",
        timeout=180,
        get_pty=True,
    )
    print(stdout.read().decode())
    # pull sample
    sftp = c.open_sftp()
    try:
        sftp.get("/tmp/probe_cap.jpg", r"C:\Users\ben_s\Projects\linx-ha-kiosk\logs\probe_cap.jpg")
        print("saved probe_cap.jpg")
    except Exception as e:
        print("no probe_cap", e)
    try:
        sftp.get("/tmp/three.nv12", r"C:\Users\ben_s\Projects\linx-ha-kiosk\logs\three.nv12")
        print("saved three.nv12")
    except Exception as e:
        print("no three", e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
