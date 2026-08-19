#!/usr/bin/env python3
"""Pull recent tablet errors from journal + dmesg."""
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

SCRIPT = r"""
echo "=== HOST / UPTIME ==="
hostname; uptime; date
echo
echo "=== FAILED UNITS ==="
systemctl --failed --no-pager || true
echo
echo "=== SERVICE STATE ==="
systemctl is-active ha-kiosk-camera-stream.service ha-kiosk-mqtt.service ha-kiosk-power.service 2>/dev/null || true
systemctl --no-pager --no-legend status ha-kiosk-camera-stream.service ha-kiosk-mqtt.service 2>/dev/null | head -n 40 || true
echo
echo "=== JOURNAL PRIORITY err+ (last 6h) ==="
journalctl -p err..alert --since "6 hours ago" --no-pager -o short-iso 2>/dev/null | tail -n 80 || true
echo
echo "=== CAMERA STREAM (last 60) ==="
journalctl -u ha-kiosk-camera-stream.service -n 60 --no-pager -o short-iso 2>/dev/null || true
echo
echo "=== MQTT (last 40) ==="
journalctl -u ha-kiosk-mqtt.service -n 40 --no-pager -o short-iso 2>/dev/null || true
echo
echo "=== DMESG errors/warnings (tail) ==="
dmesg -T --level=err,warn 2>/dev/null | tail -n 60 || dmesg -T 2>/dev/null | grep -iE 'error|fail|warn|atomisp|gc2235|oom|hung|blocked' | tail -n 60 || true
echo
echo "=== ATOMISP / CAMERA (dmesg tail) ==="
dmesg -T 2>/dev/null | grep -iE 'atomisp|gc2235|gc2355|FW_ASSERT|ISP' | tail -n 40 || true
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_check_logs.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_check_logs.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(60)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_check_logs.sh")
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
print(buf.decode("utf-8", "replace"))
c.close()
