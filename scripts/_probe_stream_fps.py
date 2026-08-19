#!/usr/bin/env python3
"""Probe MJPEG FPS by patching mqtt.env + unit, waiting for port."""
import time

import paramiko

PASS = "kiosk"


def probe(fps: int) -> None:
    script = f"""
set -e
FPS={fps}
# force in mqtt.env
python3 - <<PY
from pathlib import Path
p = Path('/opt/ha-kiosk/mqtt.env')
text = p.read_text(encoding='utf-8') if p.exists() else ''
lines = [ln for ln in text.splitlines() if not ln.startswith('CAMERA_STREAM_FPS=')]
lines.append(f'CAMERA_STREAM_FPS={fps}')
p.write_text('\\n'.join(lines).rstrip() + '\\n', encoding='utf-8')
print('mqtt.env fps set')
PY
# also unit drop-in + main-visible
mkdir -p /etc/systemd/system/ha-kiosk-camera-stream.service.d
printf '%s\\n' '[Service]' "Environment=CAMERA_STREAM_FPS=$FPS" > /etc/systemd/system/ha-kiosk-camera-stream.service.d/fps.conf
systemctl daemon-reload
systemctl restart ha-kiosk-camera-stream.service
for i in $(seq 1 20); do
  if curl -fsS --max-time 1 http://127.0.0.1:17824/health >/tmp/h.json 2>/dev/null; then
    break
  fi
  sleep 0.5
done
echo -n 'health0 '; cat /tmp/h.json; echo
systemctl show ha-kiosk-camera-stream.service -p Environment --no-pager | tr ' ' '\\n' | grep CAMERA_STREAM_FPS || true
python3 - <<'PY'
import json, time, urllib.request, threading
frames = [0]
stop = [False]
err = ['']

def suck():
    try:
        req = urllib.request.urlopen('http://127.0.0.1:17824/stream.mjpg', timeout=60)
        buf = b''
        while not stop[0]:
            chunk = req.read(8192)
            if not chunk:
                break
            buf += chunk
            while True:
                a = buf.find(b'\\xff\\xd8')
                if a < 0:
                    buf = buf[-1:]
                    break
                b = buf.find(b'\\xff\\xd9', a + 2)
                if b < 0:
                    buf = buf[a:]
                    break
                frames[0] += 1
                buf = buf[b+2:]
    except Exception as e:
        err[0] = str(e)

threading.Thread(target=suck, daemon=True).start()
time.sleep(3.0)
n0, t0 = frames[0], time.time()
time.sleep(8.0)
n1, t1 = frames[0], time.time()
stop[0] = True
got = (n1 - n0) / max(0.001, t1 - t0)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=3).read())
print('measured_fps=%.2f configured=%s frames=%s clients=%s restarts=%s suck_err=%r' % (
    got, h.get('fps'), h.get('frames'), h.get('clients'), h.get('restarts'), err[0]))
PY
uptime
ps -eo pcpu,pmem,comm | grep -E 'ffmpeg|v4l2-ctl|python3' | head -15
"""
    print(f"\n===== PROBE {fps} =====")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        "192.168.8.201",
        username="kioskuser",
        password=PASS,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = c.open_sftp()
    path = f"/tmp/_probe_fps2_{fps}.sh"
    with sftp.file(path, "w") as f:
        f.write(script)
    sftp.chmod(path, 0o755)
    sftp.close()
    chan = c.get_transport().open_session()
    chan.settimeout(120)
    chan.get_pty()
    chan.exec_command(f"echo {PASS} | sudo -S -p '' bash {path}")
    buf = b""
    deadline = time.time() + 120
    while time.time() < deadline:
        if chan.recv_ready():
            buf += chan.recv(65536)
        if chan.exit_status_ready():
            while chan.recv_ready():
                buf += chan.recv(65536)
            break
        time.sleep(0.05)
    print(buf.decode(errors="replace"))
    c.close()


if __name__ == "__main__":
    for fps in (15, 25):
        probe(fps)
