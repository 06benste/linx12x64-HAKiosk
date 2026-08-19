#!/usr/bin/env python3
"""Smoke-test power API endpoints used by the tidied drawer."""
from __future__ import annotations

import json
import sys
import time

import paramiko

HOST, PASS = "192.168.8.201", "kiosk"

REMOTE = r"""
set -euo pipefail
echo '=== deployed drawer snippet ==='
grep -n 'PANEL_WIDTH\|Screen blanked\|id="volume"\|Blank\|Night\|40px\|96px\|1\.4\.4' \
  /opt/ha-kiosk/chromium-extension/power-drawer.js \
  /opt/ha-kiosk/chromium-extension/manifest.json | head -n 40

echo '=== wait for display session ==='
for i in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:17823/status >/tmp/ha_status.json; then
    break
  fi
  sleep 1
done

python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path('/tmp/ha_status.json').read_text())
print('hostname', data.get('hostname'))
print('ha', data.get('ha'))
print('display', data.get('display'))
print('brightness', data.get('brightness'))
print('power_keys', list((data.get('power') or {}).keys())[:8])
assert 'display' in data, 'display missing from status'
disp = data['display'] or {}
assert 'blanked' in disp or 'state' in disp, disp
print('STATUS_OK')
PY

# Brightness round-trip (restore afterward)
cur=$(python3 -c "import json;print(json.load(open('/tmp/ha_status.json'))['brightness'].get('percent') or 80)")
echo "brightness_cur=$cur"
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"percent":25}' http://127.0.0.1:17823/brightness >/tmp/ha_b.json
python3 -c "import json;d=json.load(open('/tmp/ha_b.json'));print('brightness_set',d);assert d.get('ok') is True"
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d "{\"percent\":$cur}" http://127.0.0.1:17823/brightness >/dev/null

# Volume (may fail if no amixer — still report)
if curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"percent":40}' http://127.0.0.1:17823/volume >/tmp/ha_v.json; then
  python3 -c "import json;print('volume',json.load(open('/tmp/ha_v.json')))"
else
  echo 'volume_endpoint_unavailable_or_error'
  cat /tmp/ha_v.json 2>/dev/null || true
fi

# Night / Day presets
curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:17823/night-on >/tmp/ha_n.json
python3 -c "import json;print('night-on',json.load(open('/tmp/ha_n.json')))"
curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' http://127.0.0.1:17823/night-off >/tmp/ha_d.json
python3 -c "import json;print('night-off',json.load(open('/tmp/ha_d.json')))"

echo SMOKE_OK
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=25, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/drawer_smoke.sh", "w") as f:
        f.write(REMOTE.replace("\r\n", "\n"))
    sftp.chmod("/tmp/drawer_smoke.sh", 0o755)
    sftp.close()
    # Wait a moment for getty/chromium to come back after deploy restart
    time.sleep(4)
    _, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/drawer_smoke.sh", timeout=120, get_pty=True)
    print(o.read().decode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    c.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
