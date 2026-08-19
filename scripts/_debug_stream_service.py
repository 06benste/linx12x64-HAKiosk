#!/usr/bin/env python3
from __future__ import annotations
import sys, time, paramiko
HOST, PASS = "192.168.8.201", "kiosk"
REMOTE = r"""
systemctl status ha-kiosk-camera-stream.service --no-pager -l | head -40
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager
ss -ltn | grep 17824 || echo not_listening
# ensure camera power on via mqtt file
cat /opt/ha-kiosk/config/camera_power 2>/dev/null || true
systemctl restart ha-kiosk-camera-stream.service
sleep 3
ss -ltn | grep 17824 || echo still_not
journalctl -u ha-kiosk-camera-stream.service -n 20 --no-pager
"""
def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='kioskuser', password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp=c.open_sftp()
    with sftp.file('/tmp/fix-stream.sh','w') as f: f.write(REMOTE.replace('\r\n','\n'))
    sftp.chmod('/tmp/fix-stream.sh',0o755); sftp.close()
    _,o,_=c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/fix-stream.sh", timeout=60, get_pty=True)
    print(o.read().decode('utf-8','replace')); c.close()
if __name__=='__main__': main()
