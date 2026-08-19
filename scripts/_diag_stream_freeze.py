#!/usr/bin/env python3
import time
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

SCRIPT = r"""
echo === HEALTH ===
curl -fsS --max-time 3 http://127.0.0.1:17824/health || echo HEALTH_FAIL
echo
echo === SERVICE ===
systemctl is-active ha-kiosk-camera-stream.service
systemctl show ha-kiosk-camera-stream.service -p ActiveEnterTimestamp -p NRestarts -p MainPID --no-pager
echo === JOURNAL ===
journalctl -u ha-kiosk-camera-stream.service -n 100 --no-pager -o short-iso
echo === DMESG ===
dmesg -T 2>/dev/null | grep -iE 'atomisp|gc2235|gc2355|timeout|CSI|ISP|error -' | tail -50
echo === PROCS ===
ps aux | grep -E 'v4l2-ctl|ffmpeg|camera-stream' | grep -v grep
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_freeze_diag.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_freeze_diag.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(60)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_freeze_diag.sh")
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
print(buf.decode("utf-8", "replace")[-15000:])
c.close()
