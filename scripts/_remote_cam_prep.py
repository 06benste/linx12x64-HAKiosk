#!/usr/bin/env python3
import sys
import paramiko

HOST = "192.168.8.201"
PASS = "kiosk"
SCRIPT = r"""#!/bin/bash
set +e
echo "kernel=$(uname -r)"
echo "free=$(df -h / | awk 'NR==2{print $4}')"
echo '=== camera ACPI present ==='
for d in /sys/bus/acpi/devices/GCTI2355:* /sys/bus/acpi/devices/INT0310:* /sys/bus/acpi/devices/HIMX5040:* /sys/bus/acpi/devices/INT5648:*; do
  [ -d "$d" ] || continue
  printf '%s status=%s path=%s\n' "$(basename "$d")" "$(cat "$d/status" 2>/dev/null)" "$(cat "$d/path" 2>/dev/null)"
done
echo '=== ISP PCI ==='
lspci -nnk -s 00:03.0
echo '=== headers / build tools ==='
dpkg -l | awk '/linux-headers-$(uname -r)|dkms|build-essential|git/{print}'
ls /lib/modules/$(uname -r)/build 2>&1 | head
echo '=== firmware ==='
ls /lib/firmware/shisp* 2>/dev/null || echo 'no shisp'
ls /lib/firmware/intel/ipu* 2>/dev/null || true
echo '=== blacklist ==='
grep -rsl atomisp /etc/modprobe.d 2>/dev/null
lsmod | grep atomisp
"""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="kioskuser", password=PASS, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/cam-prep.sh", "w") as f:
        f.write(SCRIPT)
    sftp.chmod("/tmp/cam-prep.sh", 0o755)
    sftp.close()
    _, o, e = c.exec_command("bash /tmp/cam-prep.sh", timeout=30)
    print(o.read().decode())
    c.close()


if __name__ == "__main__":
    main()
