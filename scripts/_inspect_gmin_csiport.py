#!/usr/bin/env python3
"""Inspect gmin CsiPort lookup path on tablet source."""
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
CMD = r'''
python3 - <<'PY'
from pathlib import Path
p = Path('/usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c')
t = p.read_text()
# print quirk table region
i = t.find('GCTI2355:01_CsiPort')
print('quirk idx', i)
print(t[i-200:i+200] if i>=0 else 'no quirk')
print('---')
# find gmin_get_var_int and csi_port assignment
for key in ['gmin_get_var_int', 'gs->csi_port', 'gmin_vars', 'hardcoded', 'DMI']:
    print(key, t.count(key))
# dump function that sets csi_port
idx = t.find('gs->csi_port')
while idx >= 0:
    print('==== at', idx)
    print(t[max(0,idx-400):idx+500])
    idx = t.find('gs->csi_port', idx+1)
    if idx > 0 and t.find('gs->csi_port', idx+1) > idx+5000:
        break
# Also show gmin_get_config_var / EFI vs DSM order
for name in ['gmin_get_config_var', 'gmin_get_var_int', 'gmin_cfg_var']:
    j = t.find(f'{name}(')
    if j < 0:
        j = t.find(f'static int {name}')
        if j < 0:
            j = t.find(f'static char *{name}')
    print('FUNC', name, j)
    if j>=0:
        print(t[j:j+1200])
        print('====')
PY
'''

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file('/tmp/inspect_gmin.sh','w') as f:
    f.write(CMD)
sftp.chmod('/tmp/inspect_gmin.sh', 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/inspect_gmin.sh", timeout=60, get_pty=True)
print(o.read().decode('utf-8','replace')[:20000])
c.close()
