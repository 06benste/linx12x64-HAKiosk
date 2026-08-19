#!/usr/bin/env python3
import time
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
echo === units ===
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service || true
systemctl status ha-kiosk-camera-stream.service --no-pager -l | head -50 || true
echo === journal ===
journalctl -u ha-kiosk-camera-stream.service -n 50 --no-pager || true
echo === env ===
grep CAMERA_STREAM /opt/ha-kiosk/mqtt.env || true
systemctl show ha-kiosk-camera-stream.service -p Environment --no-pager || true
echo === try start ===
systemctl reset-failed ha-kiosk-camera-stream.service || true
systemctl start ha-kiosk-camera-stream.service || true
sleep 4
systemctl is-active ha-kiosk-camera-stream.service || true
journalctl -u ha-kiosk-camera-stream.service -n 30 --no-pager || true
curl -fsS --max-time 3 http://127.0.0.1:17824/health || echo health_fail
echo
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_fix_cam.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_fix_cam.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(60)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_fix_cam.sh")
buf = b""
deadline = time.time() + 60
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
