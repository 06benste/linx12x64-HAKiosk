#!/usr/bin/env python3
import paramiko

PASS = "kiosk"
SCRIPT = r"""
set -e
sleep 10
echo === health ===
curl -fsS --max-time 4 http://127.0.0.1:17824/health; echo
echo === ffmpeg ===
ps auxww | grep '[f]fmpeg' || echo none
echo === wrap drop-in ===
ls /etc/systemd/system/ha-kiosk-camera-stream.service.d 2>/dev/null || echo no-dropin-dir
echo === mqtt default ===
grep -n 'CAMERA_STREAM_MQTT_FPS' /opt/ha-kiosk/scripts/ha-kiosk-mqtt.py | head -3
echo === mqtt.env ===
grep CAMERA_STREAM /opt/ha-kiosk/mqtt.env
echo === snapshot hits 12s ===
journalctl -u ha-kiosk-camera-stream.service --since '12 seconds ago' --no-pager | grep -c snapshot || true
echo === mqtt journal ===
journalctl -u ha-kiosk-mqtt.service --since '12 seconds ago' --no-pager | tail -25
echo === load ===
uptime
echo === vf in server ===
python3 - <<'PY'
import importlib.util
spec=importlib.util.spec_from_file_location('css','/opt/ha-kiosk/scripts/camera-stream-server.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.build_stream_vf(m.load_look())[:180])
print('FPS', m.FPS)
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("192.168.8.201", username="kioskuser", password=PASS, timeout=15, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/_verify_load.sh", "w") as f:
    f.write(SCRIPT)
sftp.chmod("/tmp/_verify_load.sh", 0o755)
sftp.close()
chan = c.get_transport().open_session()
chan.settimeout(45)
chan.get_pty()
chan.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/_verify_load.sh")
buf = b""
import time
deadline = time.time() + 45
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
