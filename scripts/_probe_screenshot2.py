#!/usr/bin/env python3
from __future__ import annotations
import sys, paramiko
HOST, PASS = "192.168.8.201", "kiosk"
REMOTE = r"""
# As root (mqtt service style)
export DISPLAY=:0 XAUTHORITY=/home/kioskuser/.Xauthority
ffmpeg -y -f x11grab -i :0.0 -frames:v 1 -vf 'scale=960:-2' -q:v 6 -f image2 /tmp/ha-screen-root.jpg 2>&1 | tail -15
ls -la /tmp/ha-screen-root.jpg
# systemd user of mqtt
systemctl show ha-kiosk-mqtt.service -p User -p Environment --no-pager
"""
def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='kioskuser', password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp=c.open_sftp()
    with sftp.file('/tmp/probe-shot2.sh','w') as f: f.write(REMOTE.replace('\r\n','\n'))
    sftp.chmod('/tmp/probe-shot2.sh', 0o755); sftp.close()
    _,o,_=c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/probe-shot2.sh", timeout=40, get_pty=True)
    print(o.read().decode('utf-8','replace')); c.close()
if __name__=='__main__': main()
