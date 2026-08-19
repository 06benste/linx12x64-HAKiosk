#!/usr/bin/env python3
"""All-SSH post-reboot verify: install, sensors, front/rear switch."""
import pathlib
import time

import paramiko

HOST, USER, PASS = "192.168.8.201", "kioskuser", "kiosk"
ROOT = pathlib.Path(r"C:\Users\ben_s\Projects\linx-ha-kiosk")
OUT = ROOT / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    return c


def sudo_script(c, script_body: str, timeout: int = 120) -> str:
    sftp = c.open_sftp()
    with sftp.file("/tmp/_agent_job.sh", "w") as f:
        f.write("#!/bin/bash\nset -e\n" + script_body + "\n")
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
        time.sleep(0.1)
    else:
        chan.close()
        raise TimeoutError(buf.decode(errors="replace")[-800:])
    return buf.decode(errors="replace")


def main():
    c = connect()
    print("=== upload ===")
    sftp = c.open_sftp()
    for name in ("camera-stream-server.py", "gc2355_hw_exposure.py", "ha-kiosk-mqtt.py"):
        data = (ROOT / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")
        with sftp.file(f"/tmp/{name}", "wb") as f:
            f.write(data)
    sftp.close()

    print("=== install + probe ===")
    print(
        sudo_script(
            c,
            """
install -m 755 /tmp/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/gc2355_hw_exposure.py /opt/ha-kiosk/scripts/gc2355_hw_exposure.py
install -m 755 /tmp/ha-kiosk-mqtt.py /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py
echo 0 > /opt/ha-kiosk/config/camera_input
systemctl restart ha-kiosk-mqtt.service || true
# do not bounce stream unless needed — check first
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service || true
ss -ltn | grep 17824 || true
curl -fsS --max-time 4 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo ---INPUTS---
v4l2-ctl --list-inputs -d /dev/video0 || true
echo ---DMESG---
dmesg -T 2>/dev/null | grep -E 'detected [0-9]+ camera|GC2355|csi_port|port [0-9]' | tail -30 || true
grep -c camera_facing /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py || true
""",
            timeout=50,
        )
    )

    print("=== switch test on device ===")
    # Write python test on device
    test_py = r'''
import json, time, urllib.request, threading, io
from PIL import Image, ImageStat

def wake():
    def suck():
        try:
            urllib.request.urlopen("http://127.0.0.1:17824/stream.mjpg", timeout=12).read(2048)
        except Exception:
            pass
    threading.Thread(target=suck, daemon=True).start()

def snap(path):
    wake()
    time.sleep(2.5)
    data = urllib.request.urlopen("http://127.0.0.1:17824/snapshot.jpg", timeout=30).read()
    open(path, "wb").write(data)
    im = Image.open(io.BytesIO(data)).convert("RGB")
    mean = [round(x, 1) for x in ImageStat.Stat(im).mean]
    print(path, "bytes", len(data), "mean", mean)

def post(facing):
    body = json.dumps({"facing": facing}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:17824/api/input",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=90).read().decode()

print("in", urllib.request.urlopen("http://127.0.0.1:17824/api/input", timeout=10).read().decode())
snap("/tmp/sw_front.jpg")
print("to_rear", post("rear"))
time.sleep(1)
print("h", urllib.request.urlopen("http://127.0.0.1:17824/health", timeout=10).read().decode())
snap("/tmp/sw_rear.jpg")
print("to_front", post("front"))
print("h2", urllib.request.urlopen("http://127.0.0.1:17824/health", timeout=10).read().decode())
print("DONE")
'''
    sftp = c.open_sftp()
    with sftp.file("/tmp/swtest.py", "w") as f:
        f.write(test_py)
    sftp.close()
    print(sudo_script(c, "python3 /tmp/swtest.py", timeout=160))

    print("=== pull jpgs ===")
    sftp = c.open_sftp()
    for src, dst in [("/tmp/sw_front.jpg", "switch_front.jpg"), ("/tmp/sw_rear.jpg", "switch_rear.jpg")]:
        try:
            (OUT / dst).write_bytes(sftp.file(src, "rb").read())
            print("saved", dst)
        except Exception as e:
            print("miss", dst, e)
    sftp.close()
    c.close()
    print("ALL DONE")


if __name__ == "__main__":
    main()
