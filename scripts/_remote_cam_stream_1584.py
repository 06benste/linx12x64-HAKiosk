#!/usr/bin/env python3
from __future__ import annotations
import pathlib, sys
import paramiko
HOST, PASS = "192.168.8.201", "kiosk"
def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    body = pathlib.Path(__file__).with_name("_cam_stream_1584.sh").read_text(encoding="utf-8").replace("\r\n","\n")
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
    sftp=c.open_sftp()
    with sftp.file("/tmp/cam1584.sh","w") as f: f.write(body)
    sftp.chmod("/tmp/cam1584.sh", 0o755); sftp.close()
    _,o,_=c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/cam1584.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8","replace"))
    try:
        sftp=c.open_sftp(); sftp.get("/tmp/camtest.jpg","logs/camtest.jpg"); print("saved"); sftp.close()
    except Exception as e:
        print("no image", e)
    c.close()
if __name__=="__main__":
    main()
