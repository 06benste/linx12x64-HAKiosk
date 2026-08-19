#!/usr/bin/env python3
import paramiko, sys
HOST,PASS="192.168.8.201","kiosk"
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST,username="kioskuser",password=PASS,timeout=20,allow_agent=False,look_for_keys=False)
cmd="ls /usr/share/fonts/truetype/dejavu/ 2>/dev/null | head; python3 - <<'PY'\nfrom pathlib import Path\nimport importlib.util\nspec=importlib.util.spec_from_file_location('css','/opt/ha-kiosk/scripts/camera-stream-server.py')\nm=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\nprint('TIMECODE', m.TIMECODE)\nprint('vf', m.build_stream_vf(m.load_look()))\nPY"
_,o,_=c.exec_command(cmd, timeout=30)
print(o.read().decode())
c.close()
