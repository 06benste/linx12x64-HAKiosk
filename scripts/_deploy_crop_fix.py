#!/usr/bin/env python3
import io
import pathlib
import time

import numpy as np
import paramiko
from PIL import Image

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    return c


def sudo_script(c, body, timeout=80):
    sftp = c.open_sftp()
    with sftp.file("/tmp/_agent_job.sh", "w") as f:
        f.write("#!/bin/bash\n" + body + "\n")
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
    return buf.decode("utf-8", "replace")


def wrap_score(jpeg: bytes) -> dict:
    im = np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB"), dtype=np.float32)
    g = im.mean(axis=2)
    means = g.mean(axis=0)
    best = None
    for S in range(4, 120):
        l = means[:S] - means[:S].mean()
        r = means[-S:] - means[-S:].mean()
        denom = (np.linalg.norm(l) * np.linalg.norm(r)) or 1.0
        corr = float(np.dot(l, r) / denom)
        if best is None or corr > best[0]:
            best = (corr, S)
    grads = np.mean(np.abs(np.diff(g, axis=1)), axis=0)
    peak = int(np.argmax(grads[: g.shape[1] // 4]) + 1)
    return {
        "best_corr": round(best[0], 3),
        "best_S": best[1],
        "left_peak_seam": peak,
        "peak_grad": round(float(grads[peak - 1]), 2),
    }


def main():
    c = connect()
    sftp = c.open_sftp()
    with sftp.file("/tmp/camera-stream-server.py", "wb") as f:
        f.write((ROOT / "scripts" / "camera-stream-server.py").read_bytes().replace(b"\r\n", b"\n"))
    sftp.close()
    print(
        sudo_script(
            c,
            """
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
systemctl restart ha-kiosk-camera-stream.service
systemctl restart ha-kiosk-mqtt.service || true
sleep 8
curl -fsS --max-time 5 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo
python3 - <<'PY'
import importlib.util, urllib.request, threading, time
spec=importlib.util.spec_from_file_location('css','/opt/ha-kiosk/scripts/camera-stream-server.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('CROP', m.CROP_X, m.CROP_W)
print('VF', m.build_stream_vf(m.load_look())[:200])
def suck():
  try: urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=10).read(4096)
  except Exception as e: print('wake', e)
threading.Thread(target=suck, daemon=True).start()
time.sleep(3)
data=urllib.request.urlopen('http://127.0.0.1:17824/snapshot.jpg', timeout=25).read()
open('/tmp/cropfix.jpg','wb').write(data)
print('snap', len(data), data[:3])
PY
""",
            timeout=70,
        )
    )
    sftp = c.open_sftp()
    jpeg = sftp.file("/tmp/cropfix.jpg", "rb").read()
    sftp.close()
    c.close()
    (OUT / "after_cropx16.jpg").write_bytes(jpeg)
    print("metrics", wrap_score(jpeg))
    if (OUT / "live_wrap.jpg").exists():
        print("before ", wrap_score((OUT / "live_wrap.jpg").read_bytes()))


if __name__ == "__main__":
    main()
