#!/usr/bin/env python3
"""Quick redeploy stream server + verify look save / dual stream."""
from __future__ import annotations

import pathlib
import sys

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
ROOT = pathlib.Path(__file__).resolve().parents[1]

REMOTE = r"""
set -euxo pipefail
install -m 755 /tmp/ha-tuner2/camera-stream-server.py /opt/ha-kiosk/scripts/camera-stream-server.py
install -m 644 /tmp/ha-tuner2/cam-tuner.html /opt/ha-kiosk/scripts/static/cam-tuner.html
systemctl restart ha-kiosk-camera-stream.service
sleep 2
for i in $(seq 1 20); do
  curl -fsS --max-time 2 http://127.0.0.1:17824/health >/dev/null && break
  sleep 1
done
python3 - <<'PY'
import json, time, urllib.request, threading

def suck(url):
    try:
        urllib.request.urlopen(url, timeout=20).read(512)
    except Exception as e:
        print('suck_err', url, e)

threading.Thread(target=suck, args=('http://127.0.0.1:17824/stream.mjpg',), daemon=True).start()
threading.Thread(target=suck, args=('http://127.0.0.1:17824/stream.mjpg?plain=1',), daemon=True).start()
time.sleep(4)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
print('health', {k:h.get(k) for k in ('streaming','clients','frames','last_error','look')})
look = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/api/look', timeout=5).read())
sp = dict(look['software_preview'])
sp['exposure_ev'] = round(float(sp['exposure_ev']) + 0.0, 4)
body = json.dumps({'software_preview': sp}).encode()
req = urllib.request.Request('http://127.0.0.1:17824/api/look', data=body, headers={'Content-Type':'application/json'}, method='POST')
t0 = time.time()
resp = json.loads(urllib.request.urlopen(req, timeout=45).read())
print('save', resp.get('ok'), resp.get('message'), f'dt={time.time()-t0:.2f}s')
time.sleep(3)
h2 = json.loads(urllib.request.urlopen('http://127.0.0.1:17824/health', timeout=5).read())
print('after', {k:h2.get(k) for k in ('streaming','clients','frames','last_error')})
# Compare plain vs graded snapshot sizes/means quickly
from PIL import Image, ImageStat
import io
for name, q in (('graded',''),('plain','?plain=1')):
    data = urllib.request.urlopen(f'http://127.0.0.1:17824/snapshot.jpg{q}', timeout=20).read()
    im = Image.open(io.BytesIO(data)).convert('RGB')
    st = ImageStat.Stat(im)
    print(name, im.size, [round(x,1) for x in st.mean], 'bytes', len(data))
print('OK')
PY
journalctl -u ha-kiosk-camera-stream -n 25 --no-pager | tail -n 25
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.mkdir("/tmp/ha-tuner2")
    except OSError:
        pass
    for name, src in (
        ("camera-stream-server.py", ROOT / "scripts" / "camera-stream-server.py"),
        ("cam-tuner.html", ROOT / "scripts" / "static" / "cam-tuner.html"),
    ):
        with sftp.file(f"/tmp/ha-tuner2/{name}", "wb") as f:
            f.write(src.read_bytes().replace(b"\r\n", b"\n"))
    with sftp.file("/tmp/fix-tuner.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/fix-tuner.sh", 0o755)
    sftp.close()
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/fix-tuner.sh", timeout=180, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
