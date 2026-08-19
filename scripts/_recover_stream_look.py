#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp_cam_diag"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)

    def run(cmd: str) -> str:
        _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash -lc {repr(cmd)}", timeout=90, get_pty=True)
        out = o.read().decode("utf-8", "replace")
        print(out[-6000:])
        return out

    run("systemctl status ha-kiosk-camera-stream --no-pager -l | head -n 50")
    run("journalctl -u ha-kiosk-camera-stream -n 40 --no-pager")
    run("python3 -m py_compile /opt/ha-kiosk/scripts/camera_preview.py /opt/ha-kiosk/scripts/camera-stream-server.py && echo COMPILE_OK")
    run("systemctl restart ha-kiosk-camera-stream; sleep 6; systemctl is-active ha-kiosk-camera-stream; ss -ltnp | grep 17824 || true")
    run(
        "for i in 1 2 3 4 5 6 7 8; do curl -fsS --max-time 10 -o /tmp/graded.jpg http://127.0.0.1:17824/snapshot.jpg && break; sleep 1; done; "
        "curl -fsS --max-time 15 -o /tmp/plain.jpg 'http://127.0.0.1:17824/snapshot.jpg?plain=1'; "
        "python3 - <<'PY'\nfrom PIL import Image, ImageStat\nfor name in ('plain','graded'):\n im=Image.open(f'/tmp/{name}.jpg').convert('RGB'); st=ImageStat.Stat(im); print(name, im.size, [round(x,1) for x in st.mean])\nPY"
    )
    sftp = c.open_sftp()
    OUT.mkdir(exist_ok=True)
    for name in ("graded.jpg", "plain.jpg"):
        try:
            data = sftp.file(f"/tmp/{name}", "rb").read()
            (OUT / name).write_bytes(data)
            print("saved", name, len(data))
        except Exception as e:
            print("missing", name, e)
    sftp.close()
    c.close()


if __name__ == "__main__":
    main()
