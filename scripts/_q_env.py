#!/usr/bin/env python3
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
SCRIPT = r"""
echo === mqtt.env ===
grep -E 'CAMERA|INTERVAL|STREAM|SCREENSHOT|FPS' /opt/ha-kiosk/mqtt.env 2>/dev/null || echo '(no matches / missing)'
echo === stream env ===
systemctl show ha-kiosk-camera-stream.service -p Environment --no-pager
echo === wrap.conf ===
cat /etc/systemd/system/ha-kiosk-camera-stream.service.d/wrap.conf 2>/dev/null || true
echo === health ===
curl -fsS --max-time 3 http://127.0.0.1:17824/health; echo
echo === snapshot hits last 10s ===
journalctl -u ha-kiosk-camera-stream.service --since '10 seconds ago' --no-pager | grep -c snapshot || true
echo === tasks/load ===
systemctl status ha-kiosk-camera-stream.service --no-pager | head -n 20
uptime
"""
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_q.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_q.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(25)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_q.sh")
buf = b""
t = time.time() + 25
while time.time() < t:
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
