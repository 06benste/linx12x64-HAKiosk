#!/usr/bin/env python3
"""Pull graded + plain snapshots and report look stats."""
from __future__ import annotations

import io
import json
import pathlib
import sys

import paramiko
from PIL import Image, ImageStat

HOST, PASS = "192.168.8.201", "kiosk"
OUT = pathlib.Path(__file__).resolve().parents[1] / "tmp_cam_diag"
OUT.mkdir(exist_ok=True)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    cmds = [
        "cat /opt/ha-kiosk/config/camera_preview.json",
        "curl -fsS --max-time 20 -o /tmp/graded.jpg http://127.0.0.1:17824/snapshot.jpg",
        "curl -fsS --max-time 20 -o /tmp/plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'",
        "python3 - <<'PY'\nfrom PIL import Image, ImageStat\nimport json\nfor name in ('plain','graded'):\n p=f'/tmp/{name}.jpg'\n im=Image.open(p).convert('RGB')\n st=ImageStat.Stat(im)\n print(name, im.size, 'mean', [round(x,1) for x in st.mean], 'rms', [round(x,1) for x in st.rms])\nPY",
        "journalctl -u ha-kiosk-camera-stream -n 30 --no-pager",
    ]
    for cmd in cmds:
        print("====", cmd.splitlines()[0][:70], flush=True)
        _, o, e = c.exec_command(cmd, timeout=40)
        out = o.read().decode("utf-8", "replace")
        err = e.read().decode("utf-8", "replace")
        print(out or err)
    for name in ("graded.jpg", "plain.jpg"):
        local = OUT / name
        with sftp.file(f"/tmp/{name}", "rb") as f:
            local.write_bytes(f.read())
        print("saved", local, local.stat().st_size, flush=True)
    sftp.close()
    c.close()
    # Local analysis
    for name in ("plain.jpg", "graded.jpg"):
        im = Image.open(OUT / name).convert("RGB")
        st = ImageStat.Stat(im)
        print(name, im.size, "meanRGB", [round(x, 1) for x in st.mean], flush=True)


if __name__ == "__main__":
    main()
