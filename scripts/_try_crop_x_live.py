#!/usr/bin/env python3
import pathlib
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk\tmp_cam_diag")
OUT.mkdir(exist_ok=True)

REMOTE = r"""
set -x
systemctl stop ha-kiosk-camera-stream.service || true
pkill -9 -f 'v4l2-ctl --stream' || true
pkill -9 -f 'ffmpeg.*rawvideo' || true
sleep 1
/opt/ha-kiosk/scripts/load-atomisp.sh >/dev/null 2>&1 || true
sleep 1
rm -f /tmp/live.raw /tmp/frame.nv12
timeout -s KILL 12 v4l2-ctl -d /dev/video0 --set-input=0 \
  --set-fmt-video=width=1600,height=1200,pixelformat=NV12 \
  --stream-mmap=3 --stream-count=5 --stream-to=/tmp/live.raw
ls -l /tmp/live.raw
python3 -c "from pathlib import Path; FS=2842624; r=Path('/tmp/live.raw').read_bytes(); Path('/tmp/frame.nv12').write_bytes(r[-FS:][:2841600]); print(len(r), 2841600)"
# plain crops, no grade
for x in 0 16 160; do
  ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -s 1600x1184 -i /tmp/frame.nv12 \
    -vf "crop=1584:1184:${x}:0,scale=800:600" -frames:v 1 /tmp/ox_${x}.jpg && ls -l /tmp/ox_${x}.jpg
done
# roll 16
ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -s 1600x1184 -i /tmp/frame.nv12 \
  -filter_complex '[0:v]crop=1584:1184:16:0[a];[0:v]crop=16:1184:0:0[b];[a][b]hstack,scale=800:600' \
  -frames:v 1 /tmp/ox_roll16.jpg && ls -l /tmp/ox_roll16.jpg
# roll 160
ffmpeg -y -hide_banner -loglevel error -f rawvideo -pix_fmt nv12 -s 1600x1184 -i /tmp/frame.nv12 \
  -filter_complex '[0:v]crop=1440:1184:160:0[a];[0:v]crop=160:1184:0:0[b];[a][b]hstack,scale=800:600' \
  -frames:v 1 /tmp/ox_roll160.jpg && ls -l /tmp/ox_roll160.jpg
systemctl start ha-kiosk-camera-stream.service || true
echo DONE
"""


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_ox.sh", "w") as f:
        f.write(REMOTE)
    sftp.chmod("/tmp/_ox.sh", 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(100)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_ox.sh")
    buf = b""
    t = time.time() + 100
    while time.time() < t:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    print(buf.decode("utf-8", "replace")[-5000:])
    sftp = c.open_sftp()
    for name in ["ox_0.jpg", "ox_16.jpg", "ox_160.jpg", "ox_roll16.jpg", "ox_roll160.jpg"]:
        try:
            (OUT / name).write_bytes(sftp.file(f"/tmp/{name}", "rb").read())
            print("saved", name)
        except Exception as e:
            print("miss", name, e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
