#!/usr/bin/env python3
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
CMD = r"""
set -euxo pipefail
journalctl -u ha-kiosk-camera-stream.service -n 40 --no-pager | tail -n 40
echo '--- import ---'
python3 - <<'PY'
import sys
sys.path.insert(0, '/opt/ha-kiosk/scripts')
import gc2355_hw_exposure as m
print('module', m)
print('apply', m.apply_profile())
import time
time.sleep(1)
print('apply2', m.apply_profile())
PY
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/check_hw.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/check_hw.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/check_hw.sh", timeout=60, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
