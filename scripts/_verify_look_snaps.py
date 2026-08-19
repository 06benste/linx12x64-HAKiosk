#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)

    def run(cmd: str) -> str:
        _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash -lc {repr(cmd)}", timeout=120, get_pty=True)
        out = o.read().decode("utf-8", "replace")
        print(out[-7000:])
        return out

    run("systemctl is-active ha-kiosk-camera-stream; systemctl show ha-kiosk-camera-stream -p Environment --no-pager; df -h /tmp / | head")
    run("journalctl -u ha-kiosk-camera-stream -n 20 --no-pager")
    run("ps aux | grep -E 'ffmpeg|v4l2-ctl|camera-stream' | grep -v grep")
    # Use python urllib to avoid curl write issues
    run(
        "python3 - <<'PY'\n"
        "import urllib.request, time\n"
        "from PIL import Image, ImageStat\n"
        "import io, os\n"
        "base='http://127.0.0.1:17824'\n"
        "# warm up / settle\n"
        "for i in range(8):\n"
        "  data=urllib.request.urlopen(base+'/snapshot.jpg', timeout=20).read()\n"
        "  time.sleep(0.4)\n"
        "open('/tmp/graded.jpg','wb').write(data)\n"
        "plain=urllib.request.urlopen(base+'/snapshot.jpg?plain=1', timeout=20).read()\n"
        "open('/tmp/plain.jpg','wb').write(plain)\n"
        "for name in ('plain','graded'):\n"
        "  im=Image.open(f'/tmp/{name}.jpg').convert('RGB')\n"
        "  st=ImageStat.Stat(im)\n"
        "  print(name, im.size, 'mean', [round(x,1) for x in st.mean], 'bytes', os.path.getsize(f'/tmp/{name}.jpg'))\n"
        "PY"
    )
    sftp = c.open_sftp()
    for name in ("graded.jpg", "plain.jpg"):
        data = sftp.file(f"/tmp/{name}", "rb").read()
        (OUT / name).write_bytes(data)
        print("saved", name, len(data), flush=True)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
