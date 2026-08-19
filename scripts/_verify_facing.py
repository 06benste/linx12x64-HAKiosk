#!/usr/bin/env python3
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
systemctl is-active ha-kiosk-camera-stream.service || true
systemctl status ha-kiosk-camera-stream.service --no-pager -l | head -40
echo === journal ===
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager
echo === listen ===
ss -lntp | grep 17824 || true
sleep 4
curl -fsS --max-time 5 http://127.0.0.1:17824/health; echo
curl -fsS --max-time 5 http://127.0.0.1:17824/api/input; echo
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"facing":"rear"}' http://127.0.0.1:17824/api/input; echo
sleep 3
curl -fsS --max-time 5 http://127.0.0.1:17824/health; echo
curl -fsS --max-time 5 'http://127.0.0.1:17824/api/look'; echo
curl -fsS --max-time 8 -X POST -H 'Content-Type: application/json' -d '{"facing":"front"}' http://127.0.0.1:17824/api/input; echo
sleep 2
curl -fsS --max-time 5 http://127.0.0.1:17824/health; echo
grep -E 'facing|btn-rear|software look per' /opt/ha-kiosk/scripts/static/cam-tuner.html | head -5
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_verify_facing.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_verify_facing.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(70)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_verify_facing.sh")
buf = b""
deadline = time.time() + 70
while time.time() < deadline:
    if chan.recv_ready():
        buf += chan.recv(65536)
    if chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(0.05)
import sys
sys.stdout.buffer.write(buf)
c.close()
