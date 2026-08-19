#!/usr/bin/env python3
import paramiko

HOST, PASS = "192.168.8.201", "kiosk"
CMD = r"""
set -euxo pipefail
echo '=== make.log tail ==='
tail -n 80 /var/lib/dkms/atomisp/6.10-1.0.3-linx/build/make.log 2>/dev/null || tail -n 80 /var/lib/dkms/atomisp-6.10/1.0.3-linx/build/make.log 2>/dev/null || find /var/lib/dkms -name make.log | head
echo '=== patched snippet ==='
grep -n -A20 'gs->csi_port = gmin_get_var_int' /usr/src/atomisp-6.10-1.0.3-linx/atomisp/6.12/drivers/staging/media/atomisp/pci/atomisp_gmin_platform.c | head -n 40
echo '=== dkms dirs ==='
ls -la /usr/src | grep atomisp
ls -la /var/lib/dkms | grep atomisp || true
# How was it built originally?
ls /usr/src/atomisp-6.10-1.0.3-linx/dkms.conf 2>/dev/null && cat /usr/src/atomisp-6.10-1.0.3-linx/dkms.conf
ls /usr/src/atomisp-6.10-1.0.3-linx/*/dkms.conf 2>/dev/null || true
find /usr/src/atomisp-6.10-1.0.3-linx -name dkms.conf | head
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/dkms_err.sh", "w") as f:
    f.write(CMD)
sftp.chmod("/tmp/dkms_err.sh", 0o755)
sftp.close()
_, o, _ = c.exec_command(f"echo {PASS} | sudo -S -p '' bash /tmp/dkms_err.sh", timeout=60, get_pty=True)
print(o.read().decode("utf-8", "replace"))
c.close()
