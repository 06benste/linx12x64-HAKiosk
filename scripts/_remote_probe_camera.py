#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    script = r"""
set +e
K=$(uname -r)
echo "kernel $K"
echo '=== pci ==='
lspci -nnk -s 00:03.0
echo '=== config ATOMISP ==='
grep -E 'ATOMISP|INTEL_ATOMISP' /boot/config-$K 2>/dev/null || zgrep -E 'ATOMISP|INTEL_ATOMISP' /proc/config.gz 2>/dev/null || echo no-config
echo '=== modules atomisp ==='
find /lib/modules/$K -iname '*atomisp*' 2>/dev/null
echo '=== ov2680 ==='
modinfo ov2680 2>&1 | head -n 20
echo '=== i2c devices ==='
ls -l /sys/bus/i2c/devices 2>/dev/null
echo '=== blacklist ==='
cat /etc/modprobe.d/blacklist-atomisp.conf 2>/dev/null
echo '=== firmware ==='
ls -l /lib/firmware/shisp* 2>/dev/null || echo no-shisp-fw
"""
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-probe.sh", "w") as f:
        f.write(script)
    sftp.chmod("/tmp/cam-probe.sh", 0o755)
    sftp.close()
    stdin, stdout, stderr = c.exec_command("bash /tmp/cam-probe.sh", timeout=30)
    print(stdout.read().decode())
    print(stderr.read().decode()[:500])
    c.close()


if __name__ == "__main__":
    main()
